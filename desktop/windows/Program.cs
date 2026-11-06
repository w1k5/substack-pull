using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;
using System.Diagnostics;

namespace Clearview.Windows;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();
        Application.Run(new ClearviewForm());
    }
}

internal sealed class ClearviewForm : Form
{
    private readonly Label heading = new() { AutoSize = true, Text = "Clearview", Font = new Font("Segoe UI", 15, FontStyle.Bold) };
    private readonly Label status = new() { AutoSize = true, Text = "Opening Clearview…" };
    private readonly TextBox publication = new() { Width = 250, PlaceholderText = "name.substack.com" };
    private readonly Button connect = new() { AutoSize = true, Text = "Connect Substack" };
    private readonly WebView2 web = new() { Dock = DockStyle.Fill, Visible = false };
    private readonly System.Windows.Forms.Timer cookieTimer = new() { Interval = 1200 };
    private readonly HashSet<string> attemptedSessions = new(StringComparer.Ordinal);
    private Engine? engine;
    private Process? dashboardProcess;
    private Uri? dashboardUrl;
    private bool signingIn;
    private bool checkingSession;

    public ClearviewForm()
    {
        Text = "Clearview";
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        MinimumSize = new Size(920, 650);
        Size = new Size(1120, 760);
        var header = new FlowLayoutPanel {
            Dock = DockStyle.Top, AutoSize = true, Padding = new Padding(18),
            WrapContents = true, FlowDirection = FlowDirection.LeftToRight,
        };
        header.Controls.AddRange([heading, publication, connect, status]);
        Controls.Add(web);
        Controls.Add(header);
        connect.Click += async (_, _) => await BeginSignInAsync();
        cookieTimer.Tick += async (_, _) => await CheckCookiesAsync();
        FormClosing += (_, _) => {
            cookieTimer.Stop();
            if (dashboardProcess is { HasExited: false }) dashboardProcess.Kill(entireProcessTree: true);
            dashboardProcess?.Dispose();
        };
        Shown += async (_, _) => await OpenAsync();
    }

    private async Task OpenAsync()
    {
        try {
            engine = new Engine();
            using var current = await engine.ConnectionAsync("current");
            var root = current.RootElement;
            var address = root.GetProperty("publication").GetString();
            if (address is not null) publication.Text = address.Replace("https://", "");
            if (root.GetProperty("connected").GetBoolean()) await ShowDashboardAsync();
            else status.Text = "Enter your publication address to connect.";
        } catch (Exception error) { status.Text = error.Message; }
    }

    private async Task EnsureWebAsync()
    {
        if (web.CoreWebView2 is not null) return;
        if (engine is null) throw new InvalidOperationException("The data engine is unavailable.");
        try { _ = CoreWebView2Environment.GetAvailableBrowserVersionString(); }
        catch (WebView2RuntimeNotFoundException) {
            throw new InvalidOperationException("Microsoft Edge WebView2 Runtime is required. Install it from Microsoft, then reopen Clearview.");
        }
        var environment = await CoreWebView2Environment.CreateAsync(
            userDataFolder: Path.Combine(engine.DataDirectory, "WebView2"));
        await web.EnsureCoreWebView2Async(environment);
        var core = web.CoreWebView2 ?? throw new InvalidOperationException("WebView2 did not start.");
        core.NavigationStarting += (_, args) => {
            if (!Uri.TryCreate(args.Uri, UriKind.Absolute, out var url)) {
                args.Cancel = true;
                return;
            }
            if (signingIn) {
                if (url.Scheme != "https" ||
                    (url.Host != "substack.com" && !url.Host.EndsWith(".substack.com", StringComparison.OrdinalIgnoreCase)))
                    args.Cancel = true;
                return;
            }
            if (IsDashboardUrl(url)) return;
            args.Cancel = true;
            if (args.IsUserInitiated) OpenInBrowser(url);
        };
        core.NewWindowRequested += (_, args) => {
            if (signingIn) return;
            args.Handled = true;
            if (!args.IsUserInitiated || !Uri.TryCreate(args.Uri, UriKind.Absolute, out var url)) return;
            if (IsDashboardUrl(url)) core.Navigate(url.AbsoluteUri);
            else OpenInBrowser(url);
        };
    }

    private bool IsDashboardUrl(Uri url) => dashboardUrl is not null &&
        url.Scheme == dashboardUrl.Scheme &&
        url.Host.Equals(dashboardUrl.Host, StringComparison.OrdinalIgnoreCase) &&
        url.Port == dashboardUrl.Port;

    private void OpenInBrowser(Uri url)
    {
        if (url.Scheme is not ("http" or "https")) return;
        try { Process.Start(new ProcessStartInfo(url.AbsoluteUri) { UseShellExecute = true }); }
        catch { status.Text = "Could not open the link in your browser."; }
    }

    private async Task BeginSignInAsync()
    {
        if (string.IsNullOrWhiteSpace(publication.Text)) {
            status.Text = "Enter your publication address first.";
            return;
        }
        try {
            signingIn = true;
            attemptedSessions.Clear();
            connect.Enabled = false;
            await EnsureWebAsync();
            web.Visible = true;
            status.Text = "Sign in on Substack's page.";
            web.CoreWebView2.Navigate("https://substack.com/sign-in");
            cookieTimer.Start();
        } catch (Exception error) {
            signingIn = false;
            connect.Enabled = true;
            status.Text = $"Could not open sign-in: {error.Message}";
        }
    }

    private async Task CheckCookiesAsync()
    {
        if (!signingIn || checkingSession || web.CoreWebView2 is null || engine is null) return;
        checkingSession = true;
        try {
            var cookies = await web.CoreWebView2.CookieManager.GetCookiesAsync("https://substack.com/");
            foreach (var cookie in cookies) {
                if (cookie.Name is not ("substack.sid" or "connect.sid") ||
                    cookie.Domain.TrimStart('.') != "substack.com" ||
                    string.IsNullOrEmpty(cookie.Value) || !attemptedSessions.Add(cookie.Value)) continue;
                status.Text = "Checking publication access…";
                using var result = await engine.ConnectionAsync("connect", publication.Text, cookie.Value);
                signingIn = false;
                cookieTimer.Stop();
                await web.CoreWebView2.Profile.ClearBrowsingDataAsync();
                await ShowDashboardAsync();
                return;
            }
        } catch (Exception error) {
            connect.Enabled = true;
            status.Text = $"Could not connect: {error.Message}";
        } finally { checkingSession = false; }
    }

    private async Task ShowDashboardAsync()
    {
        if (engine is null) return;
        try {
            status.Text = "Opening your dashboard…";
            if (dashboardProcess is { HasExited: false }) dashboardProcess.Kill(entireProcessTree: true);
            dashboardProcess?.Dispose();
            var launched = await engine.StartDashboardAsync();
            dashboardProcess = launched.Process;
            var url = launched.Url;
            dashboardUrl = url;
            await EnsureWebAsync();
            signingIn = false;
            cookieTimer.Stop();
            publication.Visible = false;
            connect.Enabled = true;
            connect.Text = "Reconnect Substack";
            web.Visible = true;
            web.CoreWebView2.Navigate(url.ToString());
            status.Text = "Private · local";
        } catch (Exception error) {
            connect.Enabled = true;
            status.Text = error.Message;
        }
    }
}

using System.Text.Json;
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

internal sealed partial class ClearviewForm : Form
{
    // Match the dashboard's sidebar, brand mark, and page background.
    private static readonly Color Forest = Color.FromArgb(18, 53, 46);
    private static readonly Color Lime = Color.FromArgb(217, 237, 171);
    private static readonly Color Canvas = Color.FromArgb(248, 250, 247);
    private readonly Label heading = new() { AutoSize = true, Text = "Clearview", Font = new Font("Segoe UI", 15, FontStyle.Bold) };
    private readonly Label status = new() { AutoSize = true, Text = "Opening Clearview…" };
    private readonly TextBox publication = new() { Width = 250, Visible = false, PlaceholderText = "name.substack.com" };
    private readonly Button connect = new() { AutoSize = true, Text = "Sign in to Substack" };
    private sealed record PublicationChoice(string Name, string Address);
    private readonly ComboBox publications = new() { Width = 260, Visible = false, DropDownStyle = ComboBoxStyle.DropDownList, DisplayMember = "Name" };
    private readonly Button manual = new() { AutoSize = true, Visible = false, Text = "Enter publication address" };
    private string? selectionSession;
    private bool changingPublication;
    private readonly Button cancelPublication = new() { AutoSize = true, Text = "Back", Visible = false };
    private readonly WebView2 web = new() { Dock = DockStyle.Fill, Visible = false };
    private readonly System.Windows.Forms.Timer cookieTimer = new() { Interval = 1200 };
    private readonly HashSet<string> attemptedSessions = new(StringComparer.Ordinal);
    private Engine? engine;
    private Process? dashboardProcess;
    private Uri? dashboardUrl;
    private bool signingIn;
    private bool checkingSession;
    private bool choosingPublication;

    public ClearviewForm()
    {
        Text = "Clearview";
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        MinimumSize = new Size(920, 650);
        Size = new Size(1120, 760);
        BackColor = Canvas;
        var header = new FlowLayoutPanel {
            Dock = DockStyle.Top, AutoSize = true, Padding = new Padding(18),
            WrapContents = true, FlowDirection = FlowDirection.LeftToRight, BackColor = Forest,
        };
        var mark = new Label {
            Text = "↗", Size = new Size(34, 34), BackColor = Lime, ForeColor = Forest,
            TextAlign = ContentAlignment.MiddleCenter, Font = new Font("Segoe UI", 14, FontStyle.Bold),
            Margin = new Padding(0, 0, 8, 0),
        };
        heading.ForeColor = Color.White;
        heading.Margin = new Padding(0, 3, 16, 0);
        status.ForeColor = Lime;
        status.Margin = new Padding(8, 8, 0, 0);
        StyleHeaderButton(connect, Lime, Forest);
        StyleHeaderButton(manual, Forest, Color.White);
        StyleHeaderButton(cancelPublication, Forest, Color.White);
        header.Controls.AddRange([mark, heading, publications, publication, connect, manual, cancelPublication, status]);
        cancelPublication.Click += (_, _) => {
            changingPublication = false;
            publications.Visible = publication.Visible = manual.Visible = cancelPublication.Visible = false;
            connect.Enabled = web.Visible = true;
            connect.Text = "Reconnect Substack";
            status.Text = "Private · local";
        };
        Controls.Add(web);
        Controls.Add(header);
        var menu = CreateMenu();
        Controls.Add(menu);
        MainMenuStrip = menu;
        connect.Click += async (_, _) => {
            if (selectionSession is null && !changingPublication) await BeginSignInAsync();
            else {
                var address = publication.Visible ? publication.Text.Trim()
                    : (publications.SelectedItem as PublicationChoice)?.Address;
                if (string.IsNullOrEmpty(address)) status.Text = "Choose a publication or enter its address.";
                else await ConnectPublicationAsync(address, selectionSession);
            }
        };
        manual.Click += (_, _) => ShowManualPublication();
        publications.SelectionChangeCommitted += (_, _) => {
            publication.Visible = false;
            manual.Visible = true;
            connect.Text = "Open publication";
        };
        cookieTimer.Tick += async (_, _) => await CheckCookiesAsync();
        FormClosing += (_, _) => {
            cookieTimer.Stop();
            if (dashboardProcess is { HasExited: false }) dashboardProcess.Kill(entireProcessTree: true);
            dashboardProcess?.Dispose();
        };
        Shown += async (_, _) => {
            await OpenAsync();
            if (AutomaticUpdateChecks) await CheckForUpdatesAsync(true);
        };
    }

    private static void StyleHeaderButton(Button button, Color background, Color foreground)
    {
        button.FlatStyle = FlatStyle.Flat;
        button.FlatAppearance.BorderColor = Lime;
        button.BackColor = background;
        button.ForeColor = foreground;
        button.Padding = new Padding(8, 3, 8, 3);
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
        await core.AddScriptToExecuteOnDocumentCreatedAsync(
            "if (location.hostname === '127.0.0.1') " +
            "document.addEventListener('DOMContentLoaded', () => document.documentElement.classList.add('desktop-menu'), { once: true });");
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

    private async Task ChangePublicationAsync()
    {
        if (!IsDashboardOpen() || changingPublication || choosingPublication || engine is null) return;
        choosingPublication = true;
        changingPublication = true;
        connect.Enabled = false;
        web.Visible = false;
        status.Text = "Finding your publications…";
        try {
            using var discovery = await engine.ConnectionAsync("discover-saved");
            ShowPublicationChoices(discovery.RootElement);
        } catch (InvalidOperationException) {
            status.Text = "Could not load publications. Reconnect Substack and try again.";
        } finally {
            cancelPublication.Visible = true;
            choosingPublication = false;
        }
    }

    private void ShowPublicationChoices(JsonElement result)
    {
        publications.Items.Clear();
        foreach (var entry in result.GetProperty("publications").EnumerateArray()) {
            publications.Items.Add(new PublicationChoice(
                entry.GetProperty("name").GetString()!,
                entry.GetProperty("address").GetString()!));
        }
        if (publications.Items.Count == 0) {
            status.Text = "Enter your publication address.";
            ShowManualPublication();
            return;
        }
        publications.Visible = manual.Visible = connect.Enabled = true;
        connect.Text = "Open publication";
        status.Text = "Choose a publication to open.";
    }

    private async Task BeginSignInAsync()
    {
        if (checkingSession || choosingPublication) return;
        try {
            signingIn = true;
            changingPublication = cancelPublication.Visible = false;
            selectionSession = null;
            publications.Items.Clear();
            publications.Visible = publication.Visible = manual.Visible = false;
            connect.Text = "Sign in to Substack";
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
        if (!signingIn || checkingSession || choosingPublication || publications.Items.Count > 0 || web.CoreWebView2 is null || engine is null) return;
        checkingSession = true;
        string? fallbackSession = null;
        try {
            var cookies = await web.CoreWebView2.CookieManager.GetCookiesAsync("https://substack.com/");
            foreach (var cookie in cookies) {
                if (cookie.Name is not ("substack.sid" or "connect.sid") ||
                    cookie.Domain.TrimStart('.') != "substack.com" ||
                    string.IsNullOrEmpty(cookie.Value) || !attemptedSessions.Add(cookie.Value)) continue;
                status.Text = "Finding your publications…";
                selectionSession = cookie.Value;
                try {
                    using var discovery = await engine.ConnectionAsync("discover", session: cookie.Value);
                    var result = discovery.RootElement;
                    web.Visible = false;
                    cookieTimer.Stop();
                    var selected = result.GetProperty("selected").GetString();
                    ShowPublicationChoices(result);
                    if (selected is not null) await ConnectPublicationAsync(selected, cookie.Value);
                    return;
                } catch (InvalidOperationException) {
                    // The current session may still work with a manually entered address.
                }
                selectionSession = null;
                fallbackSession = cookie.Value;
            }
        } catch (Exception error) {
            connect.Enabled = true;
            status.Text = $"Could not connect: {error.Message}";
        } finally { checkingSession = false; }
        if (fallbackSession is not null) {
            selectionSession = fallbackSession;
            status.Text = "Couldn’t find a publication automatically.";
            ShowManualPublication();
        }
    }

    private void ShowManualPublication()
    {
        publications.Visible = manual.Visible = false;
        publication.Visible = connect.Enabled = true;
        connect.Text = "Connect";
        publication.Focus();
    }

    private async Task ConnectPublicationAsync(string address, string? session)
    {
        if (engine is null) return;
        choosingPublication = true;
        connect.Enabled = manual.Enabled = publications.Enabled = cancelPublication.Enabled = false;
        status.Text = "Checking publication access…";
        try {
            using var result = await engine.ConnectionAsync(changingPublication ? "switch" : "connect", address, session);
            changingPublication = cancelPublication.Visible = false;
            signingIn = false;
            selectionSession = null;
            attemptedSessions.Clear();
            cookieTimer.Stop();
            publications.Visible = publication.Visible = manual.Visible = false;
            try { await web.CoreWebView2.Profile.ClearBrowsingDataAsync(); }
            catch (InvalidOperationException) { /* The verified connection is already saved. */ }
            await ShowDashboardAsync();
        } catch (Exception error) {
            status.Text = $"Could not connect: {error.Message}";
            ShowManualPublication();
            if (publications.Items.Count > 0) {
                publications.Visible = true;
                publications.SelectedIndex = -1;
            }
        } finally {
            choosingPublication = false;
            manual.Enabled = publications.Enabled = cancelPublication.Enabled = true;
        }
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

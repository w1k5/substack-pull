using System.Diagnostics;
using System.Text.Json;

namespace Clearview.Windows;

internal sealed class Engine
{
    private readonly string executable = Path.Combine(AppContext.BaseDirectory, "engine", "clearview-engine.exe");
    private readonly string dataDirectory = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Clearview");

    public string DataDirectory => dataDirectory;

    public Engine()
    {
        Directory.CreateDirectory(dataDirectory);
        if (!File.Exists(executable))
            throw new FileNotFoundException("Clearview's data engine is missing. Reinstall the app.");
    }

    private Process CreateProcess(params string[] arguments)
    {
        var start = new ProcessStartInfo(executable) {
            WorkingDirectory = dataDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            RedirectStandardInput = true,
        };
        start.Environment["CLEARVIEW_DATA_DIR"] = dataDirectory;
        foreach (var argument in arguments) start.ArgumentList.Add(argument);
        return new Process { StartInfo = start };
    }

    public async Task<JsonDocument> ConnectionAsync(string action, string? publication = null,
                                                     string? session = null)
    {
        using var process = publication is null
            ? CreateProcess("connection", action)
            : CreateProcess("connection", action, "--publication", publication);
        process.Start();
        if (session is not null) await process.StandardInput.WriteAsync(session);
        process.StandardInput.Close();
        var output = process.StandardOutput.ReadToEndAsync();
        var error = process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync();
        var result = await output;
        _ = await error; // Never expose a possible session value from process diagnostics.
        JsonDocument document;
        try { document = JsonDocument.Parse(result); }
        catch (JsonException) { throw new InvalidOperationException("The connection check did not respond."); }
        if (process.ExitCode != 0) {
            var message = document.RootElement.TryGetProperty("error", out var detail)
                ? detail.GetString() : "Could not connect to Substack.";
            document.Dispose();
            throw new InvalidOperationException(message);
        }
        return document;
    }

    public async Task<(Process Process, Uri Url)> StartDashboardAsync()
    {
        var process = CreateProcess("dashboard", "--port", "0");
        process.Start();
        process.StandardInput.Close();
        _ = process.StandardError.ReadToEndAsync();
        try {
            var line = await process.StandardOutput.ReadLineAsync().WaitAsync(TimeSpan.FromSeconds(20));
            const string prefix = "Substack analytics: ";
            if (line is null || !line.StartsWith(prefix, StringComparison.Ordinal)
                || !Uri.TryCreate(line[prefix.Length..], UriKind.Absolute, out var url)
                || url.Scheme != "http" || url.Host != "127.0.0.1")
                throw new InvalidOperationException("The dashboard could not start.");
            return (process, url);
        } catch {
            if (!process.HasExited) process.Kill(entireProcessTree: true);
            process.Dispose();
            throw;
        }
    }
}

using System.Diagnostics;

namespace Clearview.Windows;

internal sealed partial class ClearviewForm
{
    private MenuStrip CreateMenu()
    {
        var menu = new MenuStrip { GripStyle = ToolStripGripStyle.Hidden, RenderMode = ToolStripRenderMode.System };

        var clearview = new ToolStripMenuItem("&Clearview");
        var aiConnections = new ToolStripMenuItem("AI &Connections");
        aiConnections.DropDownItems.Add("Install Claude Extension…", null,
            async (_, _) => await RunAIConnectionAsync("setup-claude"));
        aiConnections.DropDownItems.Add("Connect to Codex…", null,
            async (_, _) => await RunAIConnectionAsync("setup-codex"));
        aiConnections.DropDownItems.Add(new ToolStripSeparator());
        aiConnections.DropDownItems.Add("Copy Test Prompt", null,
            async (_, _) => await RunAIConnectionAsync("test-prompt"));
        clearview.DropDownItems.Add(aiConnections);
        clearview.DropDownOpening += (_, _) => aiConnections.Enabled = IsDashboardOpen();
        var changePublication = new ToolStripMenuItem("Change &Publication…", null,
            async (_, _) => await ChangePublicationAsync());
        clearview.DropDownItems.Add(changePublication);
        clearview.DropDownOpening += (_, _) => changePublication.Enabled = IsDashboardOpen() && !changingPublication;
        clearview.DropDownItems.Add(new ToolStripMenuItem("&Reconnect Substack…", null,
            async (_, _) => await BeginSignInAsync()) {
            ShortcutKeys = Keys.Control | Keys.Shift | Keys.R,
        });

        var edit = new ToolStripMenuItem("&Edit");
        AddEdit(edit, "&Undo", "^z", "Ctrl+Z");
        AddEdit(edit, "&Redo", "^y", "Ctrl+Y");
        edit.DropDownItems.Add(new ToolStripSeparator());
        AddEdit(edit, "Cu&t", "^x", "Ctrl+X");
        AddEdit(edit, "&Copy", "^c", "Ctrl+C");
        AddEdit(edit, "&Paste", "^v", "Ctrl+V");
        edit.DropDownItems.Add(new ToolStripSeparator());
        AddEdit(edit, "Select &All", "^a", "Ctrl+A");

        var options = new ToolStripMenuItem("&Options");
        AddDataAction(options, "Open data folder", "open");
        AddDataAction(options, "Export writing backups", "export");
        AddDataAction(options, "Clear temporary cache", "clear-cache");
        options.DropDownOpening += (_, _) => {
            foreach (ToolStripItem item in options.DropDownItems) item.Enabled = IsDashboardOpen();
        };

        var view = new ToolStripMenuItem("&View");
        var reload = new ToolStripMenuItem("&Reload", null, (_, _) => web.Reload()) {
            ShortcutKeys = Keys.Control | Keys.R,
        };
        view.DropDownItems.Add(reload);
        view.DropDownItems.Add(new ToolStripSeparator());
        var zoomIn = new ToolStripMenuItem("Zoom &In", null,
            (_, _) => web.ZoomFactor = Math.Min(2.0, web.ZoomFactor + 0.1)) {
            ShortcutKeys = Keys.Control | Keys.Shift | Keys.Oemplus,
            ShortcutKeyDisplayString = "Ctrl++",
        };
        var zoomOut = new ToolStripMenuItem("Zoom &Out", null,
            (_, _) => web.ZoomFactor = Math.Max(0.5, web.ZoomFactor - 0.1)) {
            ShortcutKeys = Keys.Control | Keys.OemMinus,
            ShortcutKeyDisplayString = "Ctrl+-",
        };
        var actualSize = new ToolStripMenuItem("&Actual Size", null,
            (_, _) => web.ZoomFactor = 1.0) {
            ShortcutKeys = Keys.Control | Keys.D0,
            ShortcutKeyDisplayString = "Ctrl+0",
        };
        view.DropDownItems.AddRange(new ToolStripItem[] { zoomIn, zoomOut, actualSize });
        void UpdateViewItems()
        {
            var available = web.Visible && web.CoreWebView2 is not null;
            foreach (ToolStripItem item in view.DropDownItems) {
                if (item is ToolStripMenuItem) item.Enabled = available;
            }
        }
        view.DropDownOpening += (_, _) => UpdateViewItems();
        web.VisibleChanged += (_, _) => UpdateViewItems();
        web.CoreWebView2InitializationCompleted += (_, _) => UpdateViewItems();
        UpdateViewItems();

        var help = new ToolStripMenuItem("&Help");
        help.DropDownItems.Add(new ToolStripMenuItem("&Clearview Help", null, (_, _) =>
            MessageBox.Show(this,
                "Use the dashboard sidebar to explore your publication, posts, Notes, and Note planner. " +
                "Choose an activity period at the top, or refresh for newer data. " +
                "If your connection expires, choose Clearview > Reconnect Substack.",
                "Clearview Help", MessageBoxButtons.OK, MessageBoxIcon.Information)) {
            ShortcutKeys = Keys.F1,
        });
        help.DropDownItems.Add(new ToolStripSeparator());
        help.DropDownItems.Add(new ToolStripMenuItem("&About Clearview", null, (_, _) =>
            MessageBox.Show(this, "Clearview beta · Substack analytics on this device.",
                "About Clearview", MessageBoxButtons.OK, MessageBoxIcon.Information)));

        menu.Items.AddRange(new ToolStripItem[] { clearview, edit, options, view, help });
        return menu;
    }

    private async Task RunAIConnectionAsync(string action)
    {
        if (engine is null) return;
        try {
            using var response = await engine.ConnectionAsync(action);
            var result = response.RootElement;
            if (result.TryGetProperty("prompt", out var prompt)) {
                Clipboard.SetText(prompt.GetString()!);
                return;
            }
            if (result.TryGetProperty("path", out var value)) {
                var path = value.GetString()!;
                try {
                    Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });
                } catch (System.ComponentModel.Win32Exception) {
                    var explorer = new ProcessStartInfo("explorer.exe") { UseShellExecute = true };
                    explorer.ArgumentList.Add(Path.GetDirectoryName(path)!);
                    Process.Start(explorer);
                }
                MessageBox.Show(this, "Finish installing in Claude Desktop. If the extension didn’t open, " +
                    "use Claude’s Install Extension command to select Clearview.mcpb.", "AI Connections");
            } else if (result.TryGetProperty("message", out var message)) {
                MessageBox.Show(this, message.GetString(), "AI Connections");
            }
        } catch (Exception error) {
            MessageBox.Show(this, error.Message, "AI Connections");
        }
    }

    private bool IsDashboardOpen() => !signingIn && web.CoreWebView2 is not null &&
        Uri.TryCreate(web.Source?.AbsoluteUri, UriKind.Absolute, out var url) && IsDashboardUrl(url);

    private void AddDataAction(ToolStripMenuItem menu, string label, string action)
    {
        menu.DropDownItems.Add(new ToolStripMenuItem(label, null, async (_, _) => {
            if (!IsDashboardOpen()) return;
            try {
                await web.ExecuteScriptAsync($"document.querySelector('[data-local-action=\"{action}\"]')?.click()");
            } catch (InvalidOperationException) {
                status.Text = "The dashboard is unavailable.";
            }
        }));
    }

    private void AddEdit(ToolStripMenuItem parent, string label, string keys, string shortcut)
    {
        // Keep native Ctrl shortcuts with the focused text field or WebView.
        var item = new ToolStripMenuItem(label, null, (_, _) => EditActive(keys)) {
            ShortcutKeyDisplayString = shortcut,
        };
        parent.DropDownItems.Add(item);
    }

    private void EditActive(string keys)
    {
        if (web.Visible && web.CoreWebView2 is not null) {
            BeginInvoke((Action)(() => {
                if (!web.Visible || web.IsDisposed) return;
                web.Focus();
                SendKeys.SendWait(keys);
            }));
            return;
        }
        if (!publication.Visible) return;
        publication.Focus();
        switch (keys) {
            case "^z": publication.Undo(); break;
            case "^x": publication.Cut(); break;
            case "^c": publication.Copy(); break;
            case "^v": publication.Paste(); break;
            case "^a": publication.SelectAll(); break;
            default: SendKeys.SendWait(keys); break;
        }
    }
}

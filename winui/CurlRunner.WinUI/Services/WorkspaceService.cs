using CurlRunner.WinUI.Models;

namespace CurlRunner.WinUI.Services;

public sealed class WorkspaceService
{
    public event EventHandler<OpenRequestEventArgs>? OpenRequestRequested;
    public event EventHandler? ResponseChanged;

    public IReadOnlyList<RequestTabSession> OpenTabs { get; private set; } = [];
    public RequestTabSession? ActiveTab { get; private set; }
    public OpenRequestEventArgs? PendingOpenRequest { get; private set; }

    public void PublishTabs(IReadOnlyList<RequestTabSession> tabs, RequestTabSession? activeTab)
    {
        OpenTabs = tabs;
        ActiveTab = activeTab;
        ResponseChanged?.Invoke(this, EventArgs.Empty);
    }

    public void RequestOpen(string name, string curl, bool newTab)
    {
        PendingOpenRequest = new OpenRequestEventArgs(name, curl, newTab);
        OpenRequestRequested?.Invoke(this, PendingOpenRequest);
    }

    public OpenRequestEventArgs? TakePendingOpenRequest()
    {
        var request = PendingOpenRequest;
        PendingOpenRequest = null;
        return request;
    }
}

public sealed record OpenRequestEventArgs(string Name, string Curl, bool NewTab);

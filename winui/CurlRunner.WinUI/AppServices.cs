using CurlRunner.WinUI.Services;

namespace CurlRunner.WinUI;

public static class AppServices
{
    public static LegacyStoreService Store { get; } = new();
    public static AppStateService State { get; } = new(Store);
    public static WorkspaceService Workspace { get; } = new();
}

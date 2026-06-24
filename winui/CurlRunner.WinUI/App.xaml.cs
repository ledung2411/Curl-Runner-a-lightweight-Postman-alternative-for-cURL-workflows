using Microsoft.UI.Xaml;

namespace CurlRunner.WinUI;

public partial class App : Application
{
    private Window? _window;
    public static MainWindow? MainWindowInstance { get; private set; }

    public App()
    {
        InitializeComponent();
        UnhandledException += (_, args) =>
        {
            var path = Path.Combine(Path.GetTempPath(), "CurlRunner.WinUI-crash.log");
            File.WriteAllText(path, args.Exception.ToString());
        };
    }

    protected override async void OnLaunched(LaunchActivatedEventArgs args)
    {
        await AppServices.State.InitializeAsync();
        MainWindowInstance = new MainWindow();
        _window = MainWindowInstance;
        _window.Activate();
    }
}

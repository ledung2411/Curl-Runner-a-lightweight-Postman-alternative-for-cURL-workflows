using CurlRunner.WinUI.Models;
using System.Collections.ObjectModel;

namespace CurlRunner.WinUI.Services;

public sealed class AppStateService
{
    private readonly LegacyStoreService _store;

    public AppStateService(LegacyStoreService store)
    {
        _store = store;
    }

    public ObservableCollection<HistoryEntry> History { get; } = [];
    public Dictionary<string, List<SavedRequest>> Collections { get; private set; } =
        new(StringComparer.OrdinalIgnoreCase);
    public Dictionary<string, Dictionary<string, string>> Environments { get; private set; } =
        new(StringComparer.OrdinalIgnoreCase);
    public List<ScenarioDefinition> Scenarios { get; private set; } = [];
    public AppSettings Settings { get; private set; } = new();
    public string ActiveEnvironment { get; private set; } = "Default";

    public event EventHandler? EnvironmentsChanged;
    public event EventHandler? CollectionsChanged;
    public event EventHandler? HistoryChanged;
    public event EventHandler? SettingsChanged;
    public event EventHandler? ScenariosChanged;

    public async Task InitializeAsync()
    {
        var history = await _store.LoadHistoryAsync();
        History.Clear();
        foreach (var entry in history)
        {
            History.Add(entry);
        }
        Collections = await _store.LoadCollectionsAsync();
        Environments = await _store.LoadEnvironmentsAsync();
        Scenarios = await _store.LoadScenariosAsync();
        Settings = await _store.LoadSettingsAsync();
        ActiveEnvironment = Environments.ContainsKey("Default")
            ? "Default"
            : Environments.Keys.First();
    }

    public IReadOnlyDictionary<string, string> ActiveVariables =>
        Environments.TryGetValue(ActiveEnvironment, out var values)
            ? values
            : new Dictionary<string, string>();

    public void SetActiveEnvironment(string name)
    {
        if (Environments.ContainsKey(name) && !string.Equals(ActiveEnvironment, name, StringComparison.Ordinal))
        {
            ActiveEnvironment = name;
            EnvironmentsChanged?.Invoke(this, EventArgs.Empty);
        }
    }

    public async Task SaveEnvironmentsAsync()
    {
        await _store.SaveEnvironmentsAsync(Environments);
        EnvironmentsChanged?.Invoke(this, EventArgs.Empty);
    }

    public async Task SaveCollectionsAsync()
    {
        await _store.SaveCollectionsAsync(Collections);
        CollectionsChanged?.Invoke(this, EventArgs.Empty);
    }

    public async Task AddHistoryAsync(HistoryEntry entry)
    {
        History.Insert(0, entry);
        while (History.Count > 500)
        {
            History.RemoveAt(History.Count - 1);
        }
        await _store.SaveHistoryAsync(History);
        HistoryChanged?.Invoke(this, EventArgs.Empty);
    }

    public async Task SaveHistoryAsync()
    {
        await _store.SaveHistoryAsync(History);
        HistoryChanged?.Invoke(this, EventArgs.Empty);
    }

    public async Task SaveSettingsAsync()
    {
        await _store.SaveSettingsAsync(Settings);
        SettingsChanged?.Invoke(this, EventArgs.Empty);
    }

    public async Task SaveScenariosAsync()
    {
        await _store.SaveScenariosAsync(Scenarios);
        ScenariosChanged?.Invoke(this, EventArgs.Empty);
    }
}

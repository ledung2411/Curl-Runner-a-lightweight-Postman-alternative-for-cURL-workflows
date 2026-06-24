using CurlRunner.WinUI.Models;
using System.Text.Json;

namespace CurlRunner.WinUI.Services;

public sealed class LegacyStoreService
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        WriteIndented = true,
    };

    public LegacyStoreService(string? dataDirectory = null)
    {
        DataDirectory = dataDirectory ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            ".curl_runner");
    }

    public string DataDirectory { get; }

    public Task<List<HistoryEntry>> LoadHistoryAsync() =>
        LoadAsync("history.json", new List<HistoryEntry>());

    public Task SaveHistoryAsync(IEnumerable<HistoryEntry> history) =>
        SaveAsync("history.json", history);

    public Task<Dictionary<string, List<SavedRequest>>> LoadCollectionsAsync() =>
        LoadAsync("collections.json", new Dictionary<string, List<SavedRequest>>(StringComparer.OrdinalIgnoreCase));

    public Task SaveCollectionsAsync(Dictionary<string, List<SavedRequest>> collections) =>
        SaveAsync("collections.json", collections);

    public async Task<Dictionary<string, Dictionary<string, string>>> LoadEnvironmentsAsync()
    {
        var environments = await LoadAsync(
            "environments.json",
            new Dictionary<string, Dictionary<string, string>>(StringComparer.OrdinalIgnoreCase));
        if (environments.Count == 0)
        {
            environments["Default"] = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        }
        return environments;
    }

    public Task SaveEnvironmentsAsync(Dictionary<string, Dictionary<string, string>> environments) =>
        SaveAsync("environments.json", environments);

    public Task<List<ScenarioDefinition>> LoadScenariosAsync() =>
        LoadAsync("scenarios.json", new List<ScenarioDefinition>());

    public Task SaveScenariosAsync(IEnumerable<ScenarioDefinition> scenarios) =>
        SaveAsync("scenarios.json", scenarios);

    public Task<AppSettings> LoadSettingsAsync() =>
        LoadAsync("settings-winui.json", new AppSettings());

    public Task SaveSettingsAsync(AppSettings settings) =>
        SaveAsync("settings-winui.json", settings);

    private async Task<T> LoadAsync<T>(string filename, T fallback)
    {
        var path = Path.Combine(DataDirectory, filename);
        if (!File.Exists(path))
        {
            return fallback;
        }
        try
        {
            await using var stream = File.OpenRead(path);
            return await JsonSerializer.DeserializeAsync<T>(stream, JsonOptions) ?? fallback;
        }
        catch
        {
            return fallback;
        }
    }

    private async Task SaveAsync<T>(string filename, T value)
    {
        Directory.CreateDirectory(DataDirectory);
        var path = Path.Combine(DataDirectory, filename);
        var temporaryPath = path + ".tmp";
        await using (var stream = new FileStream(
                         temporaryPath,
                         FileMode.Create,
                         FileAccess.Write,
                         FileShare.None,
                         4096,
                         useAsync: true))
        {
            await JsonSerializer.SerializeAsync(stream, value, JsonOptions);
        }
        File.Move(temporaryPath, path, overwrite: true);
    }
}

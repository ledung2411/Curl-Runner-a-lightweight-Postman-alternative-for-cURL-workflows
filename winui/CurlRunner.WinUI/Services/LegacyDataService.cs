using CurlRunner.WinUI.Models;
using System.Text.Json;

namespace CurlRunner.WinUI.Services;

public static class LegacyDataService
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };

    public static async Task<List<ScenarioDefinition>> LoadScenariosAsync()
    {
        var path = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            ".curl_runner",
            "scenarios.json");
        if (!File.Exists(path))
        {
            return [];
        }
        await using var stream = File.OpenRead(path);
        return await JsonSerializer.DeserializeAsync<List<ScenarioDefinition>>(stream, JsonOptions) ?? [];
    }
}

using System.Text.RegularExpressions;

namespace CurlRunner.WinUI.Services;

public static partial class EnvironmentService
{
    [GeneratedRegex(@"\{\{\s*([A-Za-z_][\w.-]*)\s*\}\}")]
    private static partial Regex VariablePattern();

    public static string Apply(string text, IReadOnlyDictionary<string, string> variables)
    {
        return VariablePattern().Replace(text ?? "", match =>
            variables.TryGetValue(match.Groups[1].Value, out var value) ? value : match.Value);
    }

    public static IReadOnlyList<string> Missing(string text, IReadOnlyDictionary<string, string> variables)
    {
        return VariablePattern().Matches(text ?? "")
            .Select(match => match.Groups[1].Value)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Where(name => !variables.ContainsKey(name))
            .OrderBy(name => name, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }
}

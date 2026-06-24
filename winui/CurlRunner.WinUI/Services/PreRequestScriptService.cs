using System.Text.RegularExpressions;

namespace CurlRunner.WinUI.Services;

public static partial class PreRequestScriptService
{
    [GeneratedRegex("""^set_env\(\s*['"](?<key>[^'"]+)['"]\s*,\s*(?<value>.+)\)\s*$""")]
    private static partial Regex SetEnvPattern();

    [GeneratedRegex("""^env\[\s*['"](?<key>[^'"]+)['"]\s*\]\s*=\s*(?<value>.+)$""")]
    private static partial Regex AssignmentPattern();

    [GeneratedRegex("""^log\(\s*(?<value>.+)\)\s*$""")]
    private static partial Regex LogPattern();

    [GeneratedRegex("""^env\.get\(\s*['"](?<key>[^'"]+)['"](?:\s*,\s*['"](?<fallback>[^'"]*)['"])?\s*\)$""")]
    private static partial Regex EnvGetPattern();

    public static ScriptResult Run(string script, IReadOnlyDictionary<string, string> environment)
    {
        var values = new Dictionary<string, string>(environment, StringComparer.OrdinalIgnoreCase);
        var logs = new List<string>();
        foreach (var rawLine in (script ?? "").Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries))
        {
            var line = rawLine.Trim();
            if (line.Length == 0 || line.StartsWith('#') || line is "import time")
            {
                continue;
            }
            var set = SetEnvPattern().Match(line);
            var assignment = AssignmentPattern().Match(line);
            var log = LogPattern().Match(line);
            if (set.Success || assignment.Success)
            {
                var match = set.Success ? set : assignment;
                var key = match.Groups["key"].Value;
                var value = Evaluate(match.Groups["value"].Value.Trim(), values);
                values[key] = value;
                logs.Add($"set_env({key})");
                continue;
            }
            if (log.Success)
            {
                logs.Add(Evaluate(log.Groups["value"].Value.Trim(), values));
                continue;
            }
            throw new InvalidOperationException(
                $"Unsupported native pre-request statement: {line}. " +
                "Supported: set_env(...), env['key']=..., log(...), env.get(...), and time.time().");
        }
        if (logs.Count > 0)
        {
            logs.Insert(0, "Pre-request script completed.");
        }
        return new ScriptResult(values, logs);
    }

    private static string Evaluate(string expression, IReadOnlyDictionary<string, string> values)
    {
        if (expression is "str(int(time.time()))" or "int(time.time())" or "time.time()")
        {
            return DateTimeOffset.UtcNow.ToUnixTimeSeconds().ToString();
        }
        var envGet = EnvGetPattern().Match(expression);
        if (envGet.Success)
        {
            return values.TryGetValue(envGet.Groups["key"].Value, out var value)
                ? value
                : envGet.Groups["fallback"].Value;
        }
        if (expression.StartsWith("env[") && expression.EndsWith(']'))
        {
            var key = expression[4..^1].Trim().Trim('\'', '"');
            return values.TryGetValue(key, out var value) ? value : "";
        }
        if (expression.StartsWith("str(") && expression.EndsWith(')'))
        {
            expression = expression[4..^1].Trim();
        }
        return expression.Trim().Trim('\'', '"');
    }
}

public sealed record ScriptResult(Dictionary<string, string> Environment, List<string> Logs);

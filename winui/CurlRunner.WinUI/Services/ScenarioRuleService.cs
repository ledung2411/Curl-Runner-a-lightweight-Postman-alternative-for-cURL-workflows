using CurlRunner.WinUI.Models;
using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace CurlRunner.WinUI.Services;

public static partial class ScenarioRuleService
{
    [GeneratedRegex(@"^([A-Za-z_]\w*)\s*=\s*(json|header|regex)\s*:(.+)$", RegexOptions.IgnoreCase)]
    private static partial Regex ExtractorPattern();

    public static (Dictionary<string, string> Values, List<string> Details) Extract(
        string rules,
        ApiResponseResult response)
    {
        var values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var details = new List<string>();
        var headers = ParseHeaders(response.Headers);
        JsonDocument? document = null;
        try
        {
            foreach (var line in ActiveLines(rules))
            {
                var match = ExtractorPattern().Match(line);
                if (!match.Success)
                {
                    throw new FormatException($"Invalid extractor: {line}");
                }
                var name = match.Groups[1].Value;
                var source = match.Groups[2].Value.ToLowerInvariant();
                var selector = match.Groups[3].Value.Trim();
                string value;
                if (source == "header")
                {
                    if (!headers.TryGetValue(selector, out value!))
                    {
                        throw new InvalidOperationException($"Extractor {name} did not find header {selector}.");
                    }
                }
                else if (source == "regex")
                {
                    var hit = Regex.Match(response.Body, selector, RegexOptions.Singleline);
                    if (!hit.Success)
                    {
                        throw new InvalidOperationException($"Extractor {name} did not match its regex.");
                    }
                    value = hit.Groups.Count > 1 ? hit.Groups[1].Value : hit.Value;
                }
                else
                {
                    document ??= JsonDocument.Parse(response.Body);
                    value = JsonValueToString(GetJsonPath(document.RootElement, selector));
                }
                values[name] = value;
                details.Add($"extract {name}={Bound(value, 80)}");
            }
            return (values, details);
        }
        finally
        {
            document?.Dispose();
        }
    }

    public static (bool Passed, List<string> Details) Assert(string rules, ApiResponseResult response)
    {
        var lines = ActiveLines(rules);
        if (lines.Count == 0)
        {
            var passed = response.StatusCode is >= 200 and < 400;
            return (passed, [$"{(passed ? "PASS" : "FAIL")}: default status 2xx/3xx"]);
        }
        var details = new List<string>();
        var headers = ParseHeaders(response.Headers);
        JsonDocument? document = null;
        try
        {
            foreach (var line in lines)
            {
                var passed = EvaluateAssertion(line, response, headers, ref document);
                details.Add($"{(passed ? "PASS" : "FAIL")}: {line}");
                if (!passed)
                {
                    return (false, details);
                }
            }
            return (true, details);
        }
        finally
        {
            document?.Dispose();
        }
    }

    private static bool EvaluateAssertion(
        string line,
        ApiResponseResult response,
        IReadOnlyDictionary<string, string> headers,
        ref JsonDocument? document)
    {
        var statusCompare = Regex.Match(line, @"^status\s*(==|!=|>=|<=|>|<)\s*(\d+)$", RegexOptions.IgnoreCase);
        if (statusCompare.Success)
        {
            return Compare(response.StatusCode, statusCompare.Groups[1].Value, int.Parse(statusCompare.Groups[2].Value));
        }
        var statusIn = Regex.Match(line, @"^status\s+in\s+(.+)$", RegexOptions.IgnoreCase);
        if (statusIn.Success)
        {
            return statusIn.Groups[1].Value.Split(',').Select(value => int.Parse(value.Trim())).Contains(response.StatusCode);
        }
        var body = Regex.Match(line, @"^body\s+(contains|not_contains)\s+(.+)$", RegexOptions.IgnoreCase);
        if (body.Success)
        {
            var contains = response.Body.Contains(StripQuotes(body.Groups[2].Value.Trim()), StringComparison.Ordinal);
            return body.Groups[1].Value.Equals("contains", StringComparison.OrdinalIgnoreCase) ? contains : !contains;
        }
        var header = Regex.Match(line, @"^header\s+([^\s]+)\s+(contains|==|!=)\s+(.+)$", RegexOptions.IgnoreCase);
        if (header.Success)
        {
            headers.TryGetValue(header.Groups[1].Value, out var actual);
            actual ??= "";
            var expected = StripQuotes(header.Groups[3].Value.Trim());
            return header.Groups[2].Value.Equals("contains", StringComparison.OrdinalIgnoreCase)
                ? actual.Contains(expected, StringComparison.Ordinal)
                : Compare(actual, header.Groups[2].Value, expected);
        }
        var jsonExists = Regex.Match(line, @"^json\s+(\S+)\s+exists$", RegexOptions.IgnoreCase);
        if (jsonExists.Success)
        {
            document ??= JsonDocument.Parse(response.Body);
            _ = GetJsonPath(document.RootElement, jsonExists.Groups[1].Value);
            return true;
        }
        var jsonCompare = Regex.Match(line, @"^json\s+(\S+)\s*(==|!=|>=|<=|>|<)\s*(.+)$", RegexOptions.IgnoreCase);
        if (jsonCompare.Success)
        {
            document ??= JsonDocument.Parse(response.Body);
            var actual = JsonValue(GetJsonPath(document.RootElement, jsonCompare.Groups[1].Value));
            var expected = Coerce(StripQuotes(jsonCompare.Groups[3].Value.Trim()));
            return Compare(actual, jsonCompare.Groups[2].Value, expected);
        }
        throw new FormatException($"Invalid assertion: {line}");
    }

    public static JsonElement GetJsonPath(JsonElement root, string path)
    {
        if (!path.StartsWith('$'))
        {
            throw new FormatException($"JSON path must start with $: {path}");
        }
        var current = root;
        foreach (Match match in Regex.Matches(path[1..], @"\.([A-Za-z_][\w-]*)|\[(\d+)\]"))
        {
            if (match.Groups[1].Success)
            {
                if (current.ValueKind != JsonValueKind.Object || !current.TryGetProperty(match.Groups[1].Value, out current))
                {
                    throw new InvalidOperationException($"JSON path not found: {path}");
                }
            }
            else
            {
                var index = int.Parse(match.Groups[2].Value);
                if (current.ValueKind != JsonValueKind.Array || current.GetArrayLength() <= index)
                {
                    throw new InvalidOperationException($"JSON path not found: {path}");
                }
                current = current[index];
            }
        }
        return current;
    }

    private static List<string> ActiveLines(string rules) => (rules ?? "")
        .Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries)
        .Select(line => line.Trim())
        .Where(line => line.Length > 0 && !line.StartsWith('#'))
        .ToList();

    private static Dictionary<string, string> ParseHeaders(string raw) => raw
        .Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries)
        .Select(line => line.Split(':', 2))
        .Where(parts => parts.Length == 2)
        .GroupBy(parts => parts[0].Trim(), StringComparer.OrdinalIgnoreCase)
        .ToDictionary(group => group.Key, group => group.Last()[1].Trim(), StringComparer.OrdinalIgnoreCase);

    private static object? JsonValue(JsonElement value) => value.ValueKind switch
    {
        JsonValueKind.String => value.GetString(),
        JsonValueKind.Number when value.TryGetInt64(out var integer) => integer,
        JsonValueKind.Number => value.GetDouble(),
        JsonValueKind.True => true,
        JsonValueKind.False => false,
        JsonValueKind.Null => null,
        _ => value.GetRawText(),
    };

    private static string JsonValueToString(JsonElement value) => JsonValue(value)?.ToString() ?? "";

    private static object? Coerce(string value)
    {
        if (value.Equals("true", StringComparison.OrdinalIgnoreCase)) return true;
        if (value.Equals("false", StringComparison.OrdinalIgnoreCase)) return false;
        if (value.Equals("null", StringComparison.OrdinalIgnoreCase)) return null;
        if (long.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var integer)) return integer;
        if (double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out var number)) return number;
        return value;
    }

    private static bool Compare(object? actual, string operation, object? expected)
    {
        if (operation == "==") return Equals(actual, expected) || string.Equals(actual?.ToString(), expected?.ToString(), StringComparison.Ordinal);
        if (operation == "!=") return !Compare(actual, "==", expected);
        if (double.TryParse(actual?.ToString(), NumberStyles.Float, CultureInfo.InvariantCulture, out var leftNumber) &&
            double.TryParse(expected?.ToString(), NumberStyles.Float, CultureInfo.InvariantCulture, out var rightNumber))
        {
            return operation switch { ">" => leftNumber > rightNumber, ">=" => leftNumber >= rightNumber, "<" => leftNumber < rightNumber, "<=" => leftNumber <= rightNumber, _ => false };
        }
        var comparison = string.Compare(actual?.ToString(), expected?.ToString(), StringComparison.Ordinal);
        return operation switch { ">" => comparison > 0, ">=" => comparison >= 0, "<" => comparison < 0, "<=" => comparison <= 0, _ => false };
    }

    private static string StripQuotes(string value) =>
        value.Length >= 2 && value[0] == value[^1] && value[0] is '\'' or '"' ? value[1..^1] : value;

    private static string Bound(string value, int length) => value.Length <= length ? value : value[..length] + "...";
}

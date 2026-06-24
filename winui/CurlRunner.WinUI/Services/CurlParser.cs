using CurlRunner.WinUI.Models;
using System.Text;

namespace CurlRunner.WinUI.Services;

public static class CurlParser
{
    public static ApiRequestDefinition Parse(string input)
    {
        var normalized = (input ?? "")
            .Replace("\\\r\n", " ")
            .Replace("\\\n", " ")
            .Replace("^\r\n", " ")
            .Replace("^\n", " ");
        var tokens = Tokenize(normalized);
        var request = new ApiRequestDefinition();
        var index = tokens.Count > 0 && tokens[0].Equals("curl", StringComparison.OrdinalIgnoreCase) ? 1 : 0;

        while (index < tokens.Count)
        {
            var token = tokens[index];
            switch (token)
            {
                case "-X":
                case "--request":
                    request.Method = RequireValue(tokens, ref index, token).ToUpperInvariant();
                    break;
                case "--url":
                    request.Url = RequireValue(tokens, ref index, token);
                    break;
                case "-H":
                case "--header":
                    AddHeader(request, RequireValue(tokens, ref index, token));
                    break;
                case "-d":
                case "--data":
                case "--data-raw":
                case "--data-ascii":
                case "--data-binary":
                    request.Body = RequireValue(tokens, ref index, token);
                    if (request.Method == "GET")
                    {
                        request.Method = "POST";
                    }
                    break;
                case "-L":
                case "--location":
                    request.FollowRedirects = true;
                    break;
                case "-k":
                case "--insecure":
                    request.VerifySsl = false;
                    break;
                case "-m":
                case "--max-time":
                    if (int.TryParse(RequireValue(tokens, ref index, token), out var timeout))
                    {
                        request.TimeoutSeconds = Math.Max(1, timeout);
                    }
                    break;
                default:
                    if (!token.StartsWith('-') && string.IsNullOrWhiteSpace(request.Url))
                    {
                        request.Url = token;
                    }
                    break;
            }
            index++;
        }

        return request;
    }

    public static string Serialize(ApiRequestDefinition request)
    {
        var lines = new List<string> { "curl" };
        if (!string.Equals(request.Method, "GET", StringComparison.OrdinalIgnoreCase))
        {
            lines.Add($"  -X {request.Method.ToUpperInvariant()}");
        }
        lines.Add($"  {Quote(request.Url)}");
        foreach (var (name, value) in request.Headers)
        {
            lines.Add($"  -H {Quote($"{name}: {value}")}");
        }
        if (!string.IsNullOrEmpty(request.Body))
        {
            lines.Add($"  --data-raw {Quote(request.Body)}");
        }
        if (!request.VerifySsl)
        {
            lines.Add("  --insecure");
        }
        if (request.FollowRedirects)
        {
            lines.Add("  --location");
        }
        if (request.TimeoutSeconds != 30)
        {
            lines.Add($"  --max-time {request.TimeoutSeconds}");
        }
        return string.Join(" \\" + Environment.NewLine, lines);
    }

    private static string Quote(string value) => $"'{value.Replace("'", "'\\''")}'";

    private static string RequireValue(IReadOnlyList<string> tokens, ref int index, string option)
    {
        index++;
        if (index >= tokens.Count)
        {
            throw new FormatException($"Missing value for {option}.");
        }
        return tokens[index];
    }

    private static void AddHeader(ApiRequestDefinition request, string raw)
    {
        var separator = raw.IndexOf(':');
        if (separator <= 0)
        {
            return;
        }
        request.Headers.Add(new(
            raw[..separator].Trim(),
            raw[(separator + 1)..].Trim()));
    }

    private static List<string> Tokenize(string input)
    {
        var tokens = new List<string>();
        var current = new StringBuilder();
        char quote = '\0';
        var escaping = false;

        foreach (var ch in input)
        {
            if (escaping)
            {
                current.Append(ch);
                escaping = false;
                continue;
            }
            if (ch == '\\' && quote != '\'')
            {
                escaping = true;
                continue;
            }
            if (quote != '\0')
            {
                if (ch == quote)
                {
                    quote = '\0';
                }
                else
                {
                    current.Append(ch);
                }
                continue;
            }
            if (ch is '\'' or '"')
            {
                quote = ch;
                continue;
            }
            if (char.IsWhiteSpace(ch))
            {
                if (current.Length > 0)
                {
                    tokens.Add(current.ToString());
                    current.Clear();
                }
                continue;
            }
            current.Append(ch);
        }

        if (escaping)
        {
            current.Append('\\');
        }
        if (quote != '\0')
        {
            throw new FormatException("Unclosed quote in cURL command.");
        }
        if (current.Length > 0)
        {
            tokens.Add(current.ToString());
        }
        return tokens;
    }
}

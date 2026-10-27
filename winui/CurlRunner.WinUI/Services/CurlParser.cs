using CurlRunner.WinUI.Models;
using System.Globalization;
using System.Text;

namespace CurlRunner.WinUI.Services;

public static class CurlParser
{
    // Short options that take a value (-XPOST, -H 'A: b'); everything else is a boolean flag (-sSLk).
    private const string ShortOptionsWithValue = "AbcCdDeEFHKmoPQrtTuUwxXyYz";

    // Long options that take a value. Options the app ignores must still be listed so
    // their value is not mistaken for the URL (for example `curl -o out.txt https://...`).
    private static readonly HashSet<string> LongOptionsWithValue = new(StringComparer.Ordinal)
    {
        "--request", "--url", "--header", "--data", "--data-raw", "--data-ascii", "--data-binary",
        "--data-urlencode", "--json", "--form", "--form-string", "--user-agent", "--user",
        "--max-time", "--oauth2-bearer", "--cookie", "--referer", "--connect-timeout", "--output",
        "--write-out", "--proxy", "--proxy-user", "--cacert", "--capath", "--cert", "--key",
        "--cert-type", "--key-type", "--pass", "--resolve", "--connect-to", "--cookie-jar",
        "--range", "--retry", "--retry-delay", "--retry-max-time", "--upload-file", "--config",
        "--limit-rate", "--speed-limit", "--speed-time", "--interface", "--dns-servers",
        "--max-redirs", "--proto", "--proto-redir", "--keepalive-time", "--unix-socket",
        "--abstract-unix-socket", "--ciphers", "--noproxy", "--preproxy", "--socks4", "--socks4a",
        "--socks5", "--socks5-hostname", "--time-cond", "--expect100-timeout", "--trace",
        "--trace-ascii", "--stderr", "--dump-header", "--continue-at", "--local-port",
        "--request-target", "--aws-sigv4", "--url-query", "--variable",
    };

    public static ApiRequestDefinition Parse(string input)
    {
        var normalized = (input ?? "")
            .Replace("\\\r\n", " ")
            .Replace("\\\n", " ")
            .Replace("^\r\n", " ")
            .Replace("^\n", " ");
        var tokens = ExpandShortOptions(Tokenize(normalized));
        var request = new ApiRequestDefinition();
        var index = tokens.Count > 0 &&
                    (tokens[0].Equals("curl", StringComparison.OrdinalIgnoreCase) ||
                     tokens[0].Equals("curl.exe", StringComparison.OrdinalIgnoreCase)) ? 1 : 0;
        var explicitMethod = false;
        var useHead = false;

        while (index < tokens.Count)
        {
            var token = tokens[index];
            switch (token)
            {
                case "-X":
                case "--request":
                    request.Method = RequireValue(tokens, ref index, token).ToUpperInvariant();
                    explicitMethod = true;
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
                    AppendBody(request, RequireValue(tokens, ref index, token));
                    break;
                case "--data-urlencode":
                    AppendBody(request, UrlEncodeData(RequireValue(tokens, ref index, token)));
                    break;
                case "--json":
                    AppendBody(request, RequireValue(tokens, ref index, token));
                    if (!HasHeader(request, "Content-Type"))
                    {
                        request.Headers.Add(new("Content-Type", "application/json"));
                    }
                    if (!HasHeader(request, "Accept"))
                    {
                        request.Headers.Add(new("Accept", "application/json"));
                    }
                    break;
                case "-A":
                case "--user-agent":
                    SetHeader(request, "User-Agent", RequireValue(tokens, ref index, token));
                    break;
                case "-u":
                case "--user":
                {
                    var credentials = RequireValue(tokens, ref index, token);
                    if (!credentials.Contains(':'))
                    {
                        credentials += ":";
                    }
                    SetHeader(request, "Authorization",
                        "Basic " + Convert.ToBase64String(Encoding.UTF8.GetBytes(credentials)));
                    break;
                }
                case "--oauth2-bearer":
                    SetHeader(request, "Authorization", $"Bearer {RequireValue(tokens, ref index, token)}");
                    break;
                case "-b":
                case "--cookie":
                {
                    var cookie = RequireValue(tokens, ref index, token);
                    if (cookie.Contains('='))
                    {
                        var existing = request.Headers.FirstOrDefault(
                            pair => pair.Key.Equals("Cookie", StringComparison.OrdinalIgnoreCase)).Value;
                        SetHeader(request, "Cookie", string.IsNullOrEmpty(existing) ? cookie : $"{existing}; {cookie}");
                    }
                    break;
                }
                case "-e":
                case "--referer":
                    SetHeader(request, "Referer", RequireValue(tokens, ref index, token).Replace(";auto", ""));
                    break;
                case "-I":
                case "--head":
                    useHead = true;
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
                    if (double.TryParse(
                            RequireValue(tokens, ref index, token),
                            NumberStyles.Float,
                            CultureInfo.InvariantCulture,
                            out var timeout))
                    {
                        request.TimeoutSeconds = Math.Max(1, (int)Math.Ceiling(timeout));
                    }
                    break;
                default:
                    if (TakesValue(token))
                    {
                        index++; // Option not used by the app: skip its value as well.
                    }
                    else if (!token.StartsWith('-') && string.IsNullOrWhiteSpace(request.Url))
                    {
                        request.Url = token;
                    }
                    break;
            }
            index++;
        }

        if (!explicitMethod)
        {
            request.Method = useHead ? "HEAD" : string.IsNullOrEmpty(request.Body) ? "GET" : "POST";
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

    private static bool TakesValue(string token) =>
        (token.Length == 2 && token[0] == '-' && ShortOptionsWithValue.Contains(token[1])) ||
        LongOptionsWithValue.Contains(token);

    // Splits attached/combined short options the way curl reads them:
    // -XPOST -> -X POST, -sSL -> -s -S -L, -sd@body.json -> -s -d @body.json.
    private static List<string> ExpandShortOptions(List<string> tokens)
    {
        var expanded = new List<string>(tokens.Count);
        var nextIsValue = false;
        foreach (var token in tokens)
        {
            if (nextIsValue || token.Length <= 2 || token[0] != '-' || token[1] == '-')
            {
                expanded.Add(token);
                nextIsValue = !nextIsValue && TakesValue(token);
                continue;
            }
            nextIsValue = false;
            for (var position = 1; position < token.Length; position++)
            {
                var letter = token[position];
                expanded.Add($"-{letter}");
                if (ShortOptionsWithValue.Contains(letter))
                {
                    if (position + 1 < token.Length)
                    {
                        expanded.Add(token[(position + 1)..]);
                    }
                    else
                    {
                        nextIsValue = true;
                    }
                    break;
                }
            }
        }
        return expanded;
    }

    private static void AppendBody(ApiRequestDefinition request, string data)
    {
        // curl joins repeated -d/--data values with '&'.
        request.Body = string.IsNullOrEmpty(request.Body) ? data : $"{request.Body}&{data}";
    }

    private static string UrlEncodeData(string value)
    {
        var separator = value.IndexOf('=');
        if (separator < 0)
        {
            return Uri.EscapeDataString(value);
        }
        var name = value[..separator];
        var content = Uri.EscapeDataString(value[(separator + 1)..]);
        return name.Length == 0 ? content : $"{name}={content}";
    }

    private static bool HasHeader(ApiRequestDefinition request, string name) =>
        request.Headers.Any(pair => pair.Key.Equals(name, StringComparison.OrdinalIgnoreCase));

    private static void SetHeader(ApiRequestDefinition request, string name, string value)
    {
        request.Headers.RemoveAll(pair => pair.Key.Equals(name, StringComparison.OrdinalIgnoreCase));
        request.Headers.Add(new(name, value));
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
                // Like bash: inside "..." a backslash only escapes " \ $ and `; otherwise it is kept,
                // so JSON escapes such as \n or \u00e9 survive -d "{\"a\":\"x\ny\"}".
                if (quote == '"' && ch is not ('"' or '\\' or '$' or '`'))
                {
                    current.Append('\\');
                }
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

using System.Globalization;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using Newtonsoft.Json.Linq;
using SixLabors.ImageSharp;
using SixLabors.ImageSharp.PixelFormats;

namespace SmallCityMastodonBot;

// Europe selection/journalling only. Rendering and Mastodon publication use Program's shared code.
internal static class EuropeDaily
{
    static readonly HashSet<long> Excluded = new() { 21512705, 27255545, 240052706 };
    static readonly Dictionary<string,string> Countries = new()
    {
        ["AL"]="Albania",["AT"]="Austria",["BA"]="Bosnia and Herzegovina",["BG"]="Bulgaria",
        ["BY"]="Belarus",["CZ"]="Czechia",["ES"]="Spain",["FI"]="Finland",["FR"]="France",
        ["GB"]="United Kingdom",["GR"]="Greece",["HR"]="Croatia",["IT"]="Italy",["LT"]="Lithuania",
        ["MD"]="Moldova",["ME"]="Montenegro",["MK"]="North Macedonia",["PL"]="Poland",
        ["PT"]="Portugal",["RO"]="Romania",["RS"]="Serbia",["SE"]="Sweden",["SI"]="Slovenia",
        ["TR"]="Türkiye",["XK"]="Kosovo",
        // All remaining country/territory codes supported by the collection scope.
        ["AD"]="Andorra",
        ["BE"]="Belgium",
        ["CH"]="Switzerland",
        ["DE"]="Germany",
        ["DK"]="Denmark",
        ["EE"]="Estonia",
        ["FO"]="Faroe Islands",
        ["GG"]="Guernsey",
        ["HU"]="Hungary",
        ["IE"]="Ireland",
        ["IM"]="Isle of Man",
        ["IS"]="Iceland",
        ["JE"]="Jersey",
        ["LI"]="Liechtenstein",
        ["LU"]="Luxembourg",
        ["LV"]="Latvia",
        ["MC"]="Monaco",
        ["MT"]="Malta",
        ["NL"]="Netherlands",
        ["NO"]="Norway",
        ["SM"]="San Marino",
        ["SK"]="Slovakia",
        ["VA"]="Vatican City"
    };
    static string Required(string name) => Environment.GetEnvironmentVariable(name) is { Length: > 0 } value
        ? value : throw new InvalidOperationException($"Missing {name}");
    static string Today => DateTimeOffset.UtcNow.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
    internal static bool Eligible(int population, int buildings) => population > 0 && population < 1000
        && buildings >= 0 && buildings <= 25 && 2 * buildings < population;
    static bool Ready(JObject state)
    {
        if ((int?)state["version"] != 1 || state["posts"] is not JArray)
            throw new InvalidOperationException("Invalid posting journal");
        if (state["pending"] is { Type: not JTokenType.Null })
            throw new InvalidOperationException("Unresolved publication: reconcile pending journal before another run");
        return !state["posts"]!.Any(p => ((string?)p["posted_at"] ?? throw new InvalidOperationException("Missing post date")).StartsWith(Today));
    }
    internal static List<JObject> Select(JArray nodes, JArray posts)
    {
        var used = posts.Select(p => (long)p["node_id"]!).ToHashSet();
        var last = (string?)posts.LastOrDefault()?["country_code"];
        var recency = new Dictionary<string,int>();
        for (int i=0;i<posts.Count;i++) recency[(string)posts[i]["country_code"]!] = i;
        var seen = new HashSet<long>();
        var groups = new Dictionary<string,List<JObject>>();
        foreach (JObject node in nodes)
        {
            long id = (long)node["id"]!;
            string code = (string?)node["country_code"] ?? "";
            if (!Countries.ContainsKey(code) || !seen.Add(id)) throw new InvalidOperationException("Invalid country or duplicate candidate");
            if (used.Contains(id) || Excluded.Contains(id) || code == last) continue;
            if (!groups.ContainsKey(code)) groups[code] = new();
            groups[code].Add(node);
        }
        var codes = groups.Keys.OrderBy(_ => Random.Shared.Next()).OrderBy(c => recency.GetValueOrDefault(c,-1)).ToList();
        foreach (var code in codes) groups[code] = groups[code].OrderBy(_ => Random.Shared.Next()).ToList();
        var result = new List<JObject>();
        for (int i=0;result.Count<50;i++)
        {
            bool added = false;
            foreach (var code in codes)
                if (i<groups[code].Count && result.Count<50) { result.Add(groups[code][i]); added=true; }
            if (!added) break;
        }
        return result;
    }
    sealed class Journal
    {
        readonly HttpClient client;
        readonly string branch, url;
        string sha = "";
        internal JObject State = new();
        internal Journal(HttpClient client)
        {
            this.client=client;
            branch=Environment.GetEnvironmentVariable("EUROPE_STATE_BRANCH") ?? "main";
            url=$"https://api.github.com/repos/{Required("GITHUB_REPOSITORY")}/contents/europe-posting-history.json";
        }
        internal async Task Load()
        {
            var payload=JObject.Parse(await client.GetStringAsync(url+"?ref="+Uri.EscapeDataString(branch)));
            sha=(string)payload["sha"]!;
            State=JObject.Parse(Encoding.UTF8.GetString(Convert.FromBase64String((string)payload["content"]!)));
        }
        internal async Task Save(JObject next)
        {
            var body=new JObject { ["message"]="Update Europe posting journal", ["branch"]=branch, ["sha"]=sha,
                ["content"]=Convert.ToBase64String(Encoding.UTF8.GetBytes(next.ToString())) };
            using var response=await client.PutAsync(url,new StringContent(body.ToString(),Encoding.UTF8,"application/json"));
            response.EnsureSuccessStatusCode();
            var payload=JObject.Parse(await response.Content.ReadAsStringAsync());
            sha=(string)payload["content"]!["sha"]!; State=next;
        }
    }
    static HttpClient Client()
    {
        var client=new HttpClient { Timeout=TimeSpan.FromSeconds(90) };
        client.DefaultRequestHeaders.UserAgent.ParseAdd("SmallTownEurope/1.0 (+https://en.osm.town/@SmallTownEurope)");
        return client;
    }
    static async Task<int> Count(HttpClient client, JObject node)
    {
        var endpoint=new Uri(Required("OVERPASS_PRIMARY_URL"));
        if (endpoint.Scheme!="https") throw new InvalidOperationException("HTTPS Overpass endpoint required");
        string lat=((double)node["lat"]!).ToString(CultureInfo.InvariantCulture);
        string lon=((double)node["lon"]!).ToString(CultureInfo.InvariantCulture);
        using var response=await client.PostAsync(endpoint,new FormUrlEncodedContent(new Dictionary<string,string> {
            ["data"]=$"[out:json][timeout:60];nwr(around:800,{lat},{lon})[\"building\"];out count;" }));
        response.EnsureSuccessStatusCode();
        return ParseCount(JObject.Parse(await response.Content.ReadAsStringAsync()));
    }
    internal static int ParseCount(JObject data)
    {
        if (data["remark"] != null) throw new InvalidOperationException("Overpass returned an error");
        var date=DateTimeOffset.Parse((string)data["osm3s"]!["timestamp_osm_base"]!,CultureInfo.InvariantCulture);
        double age=(DateTimeOffset.UtcNow-date).TotalSeconds;
        if (age < -300 || age > 48*3600) throw new InvalidOperationException("Stale Overpass snapshot");
        var elements=(JArray)data["elements"]!;
        if (elements.Count!=1 || (string?)elements[0]["type"]!="count") throw new InvalidOperationException("Incomplete building count");
        var tags=elements[0]["tags"]!;
        int total=int.Parse((string)tags["total"]!,CultureInfo.InvariantCulture);
        var counts=new[]{"nodes","ways","relations"}.Select(k=>int.Parse((string)tags[k]!,CultureInfo.InvariantCulture)).ToArray();
        if (counts.Any(n=>n<0) || counts.Sum(n=>(long)n)!=total) throw new InvalidOperationException("Invalid building count");
        return total;
    }
    internal static void ValidateTile(Image<Rgba32> image)
    {
        if (image.Width!=256 || image.Height!=256) throw new InvalidOperationException("Unexpected map tile dimensions");
        byte[] pixels=new byte[256*256*4];
        image.CopyPixelDataTo(pixels);
        // Exact pixels of the HTTP-success error image observed in run 45039931108.
        if (Convert.ToHexString(SHA256.HashData(pixels))=="16FF781EC623CF0D2698D498C83865919950ACA88B2AD72EA53DC62F222045AC")
            throw new InvalidOperationException("OSM returned an Access blocked tile. No post generated; resolve tile access with the maintainer.");
    }
    internal static async Task Run(string[] args)
    {
        if (args.Any(a=>a!="--publish")) throw new ArgumentException("Use /europe [--publish]");
        bool publish=args.Contains("--publish");
        if (publish && (Environment.GetEnvironmentVariable("EUROPE_ENABLE_POSTING")!="true" || Required("EUROPE_STATE_BRANCH")!="main"))
            throw new InvalidOperationException("Publishing requires main and EUROPE_ENABLE_POSTING=true");
        using var github=Client();
        github.DefaultRequestHeaders.Authorization=new AuthenticationHeaderValue("Bearer",Required("GH_TOKEN"));
        var journal=new Journal(github); await journal.Load();
        if (!Ready(journal.State)) { Console.WriteLine("Already posted today; skipping."); return; }
        using var api=Client(); using var tiles=Client();
        var data=JObject.Parse(await File.ReadAllTextAsync("townsList_Europe_countries.json"));
        var start=DateTimeOffset.UtcNow;
        File.Delete("europe-preview.png"); File.Delete("europe-post.txt");
        foreach (var node in Select((JArray)data["elements"]!, (JArray)journal.State["posts"]!))
        {
            if (DateTimeOffset.UtcNow-start>TimeSpan.FromMinutes(10)) break;
            int pop=int.Parse((string)node["tags"]!["population"]!,CultureInfo.InvariantCulture);
            if (pop<1 || pop>999) continue;
            int count=await Count(api,node);
            if (!Eligible(pop,count)) { Console.WriteLine($"Rejected {node["id"]}: {count} buildings"); await Task.Delay(10000); continue; }
            double lat=(double)node["lat"]!,lon=(double)node["lon"]!;
            string code=(string)node["country_code"]!;
            string text=FormattableString.Invariant($"{node["tags"]!["name"]}, {Countries[code]} seems like it could use some mapping!\n\nPopulation: {pop}\nBuilding count: {count}\n\nMap link: https://www.openstreetmap.org/#map=16/{lat}/{lon}\n#OpenStreetMap");
            await File.WriteAllTextAsync("europe-post.txt",text);
            await Program.GenerateImageFromOSMTiles(tiles,16,lat,lon,"europe-preview.png");
            Console.WriteLine(text);
            if (!publish) { Console.WriteLine("Preview only: no publication or history update."); return; }
            string token=Required("MASTODON_API_KEY_EU");
            var account=await new Mastonet.MastodonClient("en.osm.town",token,api).GetCurrentUser();
            if (!string.Equals(account.AccountName,"SmallTownEurope",StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("Wrong Mastodon account");
            if (!Ready(journal.State)) throw new InvalidOperationException("Already posted today");
            var next=(JObject)journal.State.DeepClone();
            next["pending"]=new JObject { ["node_id"]=(long)node["id"]!,["country_code"]=code,["text"]=text,["started_at"]=DateTimeOffset.UtcNow.ToString("O") };
            await journal.Save(next); // Reservation must succeed BEFORE uploading or posting.
            string status=await Program.PostTown(api,text,token,await File.ReadAllBytesAsync("europe-preview.png"),"europe-preview.png","OpenStreetMap view of the featured settlement at posting time.");
            if (string.IsNullOrWhiteSpace(status)) throw new InvalidOperationException("Missing status ID; reconcile pending journal");
            next=(JObject)journal.State.DeepClone();
            ((JArray)next["posts"]!).Add(new JObject { ["node_id"]=(long)node["id"]!,["country_code"]=code,["status_id"]=status,["posted_at"]=DateTimeOffset.UtcNow.ToString("O") });
            next["pending"]=null; await journal.Save(next);
            Console.WriteLine("Published status "+status); return;
        }
        throw new InvalidOperationException("No eligible town in bounded search; nothing posted");
    }
    internal static void SelfTest()
    {
        static void Check(bool ok) { if (!ok) throw new Exception("Europe self-test failed"); }
        Check(Eligible(51,25) && !Eligible(50,25) && !Eligible(999,26) && !Eligible(0,0) && !Eligible(1000,0) && !Eligible(50,-1));
        var nodes=JArray.Parse("[{id:1,country_code:'FR'},{id:2,country_code:'ES'},{id:3,country_code:'GR'},{id:4,country_code:'FR'}]");
        var posts=JArray.Parse("[{node_id:1,country_code:'FR'},{node_id:2,country_code:'ES'}]");
        var selected=Select(nodes,posts);
        Check(selected.Count==2 && (long)selected[0]["id"]! ==3 && (long)selected[1]["id"]! ==4);
        Check(Select(JArray.Parse("[{id:5,country_code:'ES'}]"),posts).Count==0);
        Check(Select(JArray.Parse("[{id:6,country_code:'DE'},{id:7,country_code:'NO'},{id:8,country_code:'CH'}]"),new JArray()).Count==3);
        var state=JObject.Parse("{version:1,posts:[],pending:null}"); Check(Ready(state));
        state["pending"]=new JObject();
        bool blocked=false; try { Ready(state); } catch (InvalidOperationException) { blocked=true; } Check(blocked);
        state["pending"]=null; ((JArray)state["posts"]!).Add(new JObject { ["posted_at"]=Today+"T00:00:00Z" }); Check(!Ready(state));
        var count=new JObject { ["osm3s"]=new JObject { ["timestamp_osm_base"]=DateTimeOffset.UtcNow.ToString("O") }, ["elements"]=JArray.Parse("[{type:'count',tags:{nodes:'1',ways:'2',relations:'0',total:'3'}}]") };
        Check(ParseCount(count)==3); count["elements"]![0]!["tags"]!["total"]="0";
        blocked=false; try { ParseCount(count); } catch (InvalidOperationException) { blocked=true; } Check(blocked);
        Console.WriteLine("Europe C# checks passed: thresholds, rotation, repeats, pending/daily gate, count validation.");
    }
}

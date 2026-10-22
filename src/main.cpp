// artem.gd-proxy
// Routes ALL of Geometry Dash's own HTTP traffic (levels, level lists,
// music, song info, leaderboards) through a local proxy so downloads
// succeed on the first attempt.
//
// How it works: GD downloads through cocos2d-x CCHttpClient, which is
// libcurl underneath. libcurl honours the standard proxy environment
// variables (http_proxy / https_proxy / all_proxy) when no explicit
// CURLOPT_PROXY is set, and cocos2d-x never sets one. So pointing the
// process at a localhost proxy is enough - no WndProc, no raw input, no
// hooks into libcocos2d.dll (whose CCHttpClient symbols are not bound in
// the 2.2091 dataset anyway).
//
// The bundled tools/gdproxy.py is a tiny local HTTP(S) proxy that:
//   - retries upstream requests a few times with backoff, and
//   - caches every successful response on disk.
// The retry turns "first attempt fails, second succeeds" into "first
// attempt succeeds". The cache turns repeat downloads into instant hits.
//
// Important nuance: Geometry Dash's level data server (www.boomlings.com)
// sits behind Cloudflare, which trusts the game's own HTTP client but
// blocks scripted proxies. So by default the mod sets NO_PROXY for
// boomlings.com - level requests keep using the game's direct connection
// (and the game's own retry), while everything else (music, song info,
// Newgrounds, leaderboards, etc.) goes through the caching proxy. This
// "direct-hosts" list is a setting you can change.
//
// The mod itself only sets environment variables when the user has
// configured a proxy-url setting. Empty default = no behaviour change.

#include <Geode/Geode.hpp>
#include <cstdlib>
#include <algorithm>

using namespace geode::prelude;

namespace {
    std::string normalizeProxy(std::string proxy) {
        // trim whitespace
        auto notspace = [](char c) { return !std::isspace(static_cast<unsigned char>(c)); };
        proxy.erase(proxy.begin(), std::find_if(proxy.begin(), proxy.end(), notspace));
        proxy.erase(std::find_if(proxy.rbegin(), proxy.rend(), notspace).base(), proxy.end());
        if (proxy.empty()) return proxy;
        // add http:// scheme if none was given
        if (proxy.find("://") == std::string::npos) {
            proxy = "http://" + proxy;
        }
        // strip trailing slash (curl does not care, but keep it tidy)
        while (proxy.size() > 1 && proxy.back() == '/') proxy.pop_back();
        return proxy;
    }
}

$on_mod(Loaded) {
    auto proxy = Mod::get()->getSettingValue<std::string>("proxy-url");
    proxy = normalizeProxy(proxy);
    if (proxy.empty()) {
        log::info("GD Proxy Helper: no proxy-url setting, proxy disabled");
        return;
    }
    // Must use the CRT _putenv_s: libcurl reads the CRT environment via
    // getenv(). SetEnvironmentVariable would NOT be visible to it.
    _putenv_s("HTTP_PROXY", proxy.c_str());
    _putenv_s("HTTPS_PROXY", proxy.c_str());
    _putenv_s("ALL_PROXY", proxy.c_str());
    _putenv_s("http_proxy", proxy.c_str());
    _putenv_s("https_proxy", proxy.c_str());
    log::info("GD Proxy Helper: GD traffic routed through {}", proxy);
    // Hosts that must keep the game's own direct connection (Cloudflare
    // trusts the game client but blocks proxies). libcurl no_proxy accepts
    // comma-separated domains; a leading '.' matches subdomains.
    auto direct = Mod::get()->getSettingValue<std::string>("direct-hosts");
    if (!direct.empty()) {
        _putenv_s("NO_PROXY", direct.c_str());
        _putenv_s("no_proxy", direct.c_str());
        log::info("GD Proxy Helper: direct hosts (bypass proxy): {}", direct);
    }
}

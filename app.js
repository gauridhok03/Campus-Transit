/* Campus Transit - small beginner-friendly JavaScript.
   1. Auto-refresh ("polling"): every 10 s fetch fresh HTML fragments and swap them in.
   2. Live route search + quick area buttons.
   3. Route page: Home->College / College->Home tabs.
   4. Notifications: bell counter, "NEW" tags and pop-up alerts when something changes.
   5. Leaflet maps (route page: route line + stops + moving bus; live page: all buses) with an offline fallback.
   6. Admin helpers (copy the reason, confirm dialogs).
*/
(function () {
  "use strict";
  var POLL_SECONDS = 10, SEEN_KEY = "ct_last_seen";
  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };
  var TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png", ATTR = "&copy; OpenStreetMap contributors";

  // ---------- notifications: seen / NEW tags / bell / toasts ----------
  function lastSeen() { var v = localStorage.getItem(SEEN_KEY); return v === null ? null : parseInt(v, 10); }
  function markNew(root) {
    var seen = lastSeen();
    $$(".notif[data-id]", root || document).forEach(function (li) {
      li.classList.toggle("is-new", seen !== null && parseInt(li.dataset.id, 10) > seen);
    });
  }
  var notifPage = $("#notif-page");
  if (notifPage) { localStorage.setItem(SEEN_KEY, notifPage.dataset.latestId); }

  var toastedUpTo = null;
  function toast(item) {
    var box = $("#toasts"); if (!box) return;
    var el = document.createElement("div"); el.className = "toast"; el.setAttribute("role", "status");
    var change = (item.old || item["new"]) ? '<div class="t-change">' + (item.old || "—") + " → " + (item["new"] || "—") + "</div>" : "";
    el.innerHTML = "<b>🔔 Route " + item.route + ": " + item.type + "</b><span></span>" + change + "<small>Click to view</small>";
    el.querySelector("span").textContent = item.text;
    el.addEventListener("click", function () { location.href = "/notifications"; });
    box.appendChild(el);
    setTimeout(function () { el.classList.add("out"); setTimeout(function () { el.remove(); }, 320); }, 9000);
  }
  function checkNotifications() {
    var seen = lastSeen();
    fetch("/api/notifications/summary" + (seen === null ? "" : "?after=" + seen), { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (seen === null) { localStorage.setItem(SEEN_KEY, data.latest_id); toastedUpTo = data.latest_id; return; }
        var bell = $("#bell-count");
        if (bell) { bell.textContent = data.new_count > 99 ? "99+" : data.new_count; bell.hidden = data.new_count === 0 || !!notifPage; }
        if (toastedUpTo === null) toastedUpTo = seen;                // first run: do not pop up old news
        if (!notifPage) data.items.slice().reverse().forEach(function (item) { if (item.id > toastedUpTo) toast(item); });
        toastedUpTo = Math.max(toastedUpTo, data.latest_id);
        if (notifPage) localStorage.setItem(SEEN_KEY, data.latest_id);
        markNew();
      }).catch(function () {});
  }

  // ---------- polling ----------
  var elements = $$("[data-poll-url]");
  function buildUrl(el) {
    var url = el.dataset.pollUrl, box = el.dataset.pollSearch ? $(el.dataset.pollSearch) : null;
    if (box) url += (url.indexOf("?") === -1 ? "?" : "&") + (el.dataset.pollParam || "q") + "=" + encodeURIComponent(box.value.trim());
    return url;
  }
  function showNetworkProblem(show) { var b = $("#net-banner"); if (b) b.hidden = !show; }
  function stamp() { var s = $("#last-refreshed"); if (s) s.textContent = new Date().toLocaleTimeString(); }
  function refresh(el, showLoading) {
    if (showLoading) el.classList.add("is-loading");
    return fetch(buildUrl(el), { headers: { "X-Requested-With": "fetch" }, cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.text(); })
      .then(function (html) {
        el.innerHTML = html; showNetworkProblem(false); stamp();
        if (el.dataset.afterUpdate === "map") updateRouteMap();
        if (el.id === "route-info") applyTab();
        markNew(el);
      })
      .catch(function () { showNetworkProblem(true); })
      .then(function () { el.classList.remove("is-loading"); });
  }
  if (elements.length || $("#live-map")) {
    var note = $("#live-note"); if (note) note.hidden = false;
    setInterval(function () { if (!document.hidden) elements.forEach(function (el) { refresh(el, false); }); }, POLL_SECONDS * 1000);
  }
  setInterval(function () { if (!document.hidden) checkNotifications(); }, POLL_SECONDS * 1000);
  checkNotifications(); markNew();

  // ---------- live search + quick area buttons ----------
  var searchBox = $("#route-search"), routeList = $("#route-list");
  if (searchBox && routeList) {
    var timer;
    searchBox.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        var q = searchBox.value.trim(), params = new URLSearchParams(location.search);
        if (q) params.set("q", q); else params.delete("q");
        var qs = params.toString(); history.replaceState(null, "", qs ? "?" + qs : location.pathname);
        refresh(routeList, true);
      }, 300);
    });
  }
  $$("[data-fill]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var target = $(btn.dataset.target || "#route-search"); if (!target) return;
      target.value = btn.dataset.fill; target.dispatchEvent(new Event("input"));
    });
  });

  // ---------- route page tabs ----------
  var activeTab = null;
  function applyTab() {
    var tabs = $$(".tab"); if (!tabs.length) return;
    if (!activeTab) activeTab = new Date().getHours() < 12 ? "to" : "from";   // morning -> Home->College, else College->Home
    tabs.forEach(function (t) { t.classList.toggle("on", t.dataset.tab === activeTab); t.setAttribute("aria-selected", t.dataset.tab === activeTab); });
    $$(".tab-pane").forEach(function (p) { p.hidden = p.dataset.pane !== activeTab; });
  }
  document.addEventListener("click", function (e) { var tab = e.target.closest(".tab"); if (tab) { activeTab = tab.dataset.tab; applyTab(); } });
  applyTab();

  // ---------- map of one route: route line + stops + moving bus ----------
  var map = null, marker = null, routeDrawn = false;
  function busIcon(status, small) {
    return L.divIcon({ html: "🚌", className: "bus-icon bus-" + status + (small ? " small" : ""), iconSize: small ? [26, 26] : [34, 34], iconAnchor: small ? [13, 13] : [17, 17] });
  }
  function updateRouteMap() {
    var mapEl = $("#map"), data = $("#loc-data"), mapNote = $("#map-note");
    if (!mapEl || !data) return;
    var lat = parseFloat(data.dataset.lat), lon = parseFloat(data.dataset.lon);
    var geo = {}; try { geo = JSON.parse($("#route-geo").textContent); } catch (e) {}
    var stops = geo.stops || [];
    if (isNaN(lat) || isNaN(lon)) {                                        // missing coordinates -> no bus marker
      if (marker && map) { map.removeLayer(marker); marker = null; }
      if (!stops.length || typeof L === "undefined") {
        mapEl.hidden = true; if (mapNote) { mapNote.hidden = false; mapNote.textContent = "No map marker: the bus location is unavailable."; } return;
      }
    }
    if (typeof L === "undefined") { mapEl.hidden = true; if (mapNote) { mapNote.hidden = false; mapNote.textContent = "The map could not be loaded (internet needed for the map). The coordinates above are still correct."; } return; }
    mapEl.hidden = false;
    if (mapNote) { mapNote.hidden = isNaN(lat) ? false : true; if (isNaN(lat)) mapNote.textContent = "No bus marker: the bus location is unavailable (the route is still shown)."; }
    if (!map) {
      map = L.map("map");
      L.tileLayer(TILES, { maxZoom: 19, attribution: ATTR }).addTo(map);
    }
    if (!routeDrawn && stops.length) {
      var pts = stops.map(function (s) { return [s.lat, s.lon]; });
      L.polyline(pts, { color: geo.color || "#0f8f7e", weight: 5, opacity: .75 }).addTo(map);
      stops.forEach(function (s, i) {
        L.marker([s.lat, s.lon], { icon: L.divIcon({ className: "", html: '<div class="stop-dot" style="--rc:' + (geo.color || "#0f9d8a") + '"></div>', iconSize: [12, 12], iconAnchor: [6, 6] }) })
          .bindTooltip((i === 0 ? "🎓 " : "") + s.name).addTo(map);
      });
      map.fitBounds(L.latLngBounds(pts).pad(0.15)); routeDrawn = true;
    }
    if (!isNaN(lat) && !isNaN(lon)) {
      var locationLabel = data.dataset.live === "true" && data.dataset.status === "current" ? "LIVE – Location Sharing Active" :
        (data.dataset.tripStatus === "Trip Ended" ? "Trip Ended · last shared position" : "SIMULATED location (" + data.dataset.label + ")");
      var text = "<strong>" + data.dataset.bus + "</strong><br>" + locationLabel + (data.dataset.near ? "<br>Near " + data.dataset.near : "");
      if (!marker) { marker = L.marker([lat, lon], { icon: busIcon(data.dataset.status), zIndexOffset: 1000 }).addTo(map); if (!routeDrawn) map.setView([lat, lon], 14); }
      else marker.setLatLng([lat, lon]).setIcon(busIcon(data.dataset.status));
      marker.bindPopup(text);
      if ($("#driver-start-tracking")) map.panTo([lat, lon], { animate: false });
    }
    map.invalidateSize();
  }
  updateRouteMap();

  // ---------- driver GPS trip controls ----------
  var driverActions = $(".driver-actions"), driverStart = $("#driver-start-tracking"),
      driverStop = $("#driver-stop-tracking"), driverMessage = $("#driver-location-message");
  if (driverActions && driverStart && driverStop) {
    var trackingWatch = null, trackingRequested = false, driverLocation = $("#loc-data"),
        serverTracking = driverLocation.dataset.live === "true", locationQueue = Promise.resolve();
    var displayTime = function (value) {
      return value ? new Date(value.replace(" ", "T")).toLocaleString() : "—";
    };
    var setDriverMessage = function (text, error) {
      driverMessage.textContent = text;
      driverMessage.classList.toggle("is-error", !!error);
    };
    var updateDriverLocation = function (position) {
      if (!trackingRequested) return;
      var lat = position.coords.latitude, lon = position.coords.longitude, stamp = new Date().toISOString();
      driverLocation.dataset.lat = lat;
      driverLocation.dataset.lon = lon;
      driverLocation.dataset.live = "true";
      driverLocation.dataset.status = "current";
      driverLocation.dataset.label = "Current";
      driverLocation.dataset.tripStatus = "In Progress";
      $("#driver-current-location").textContent = lat.toFixed(5) + ", " + lon.toFixed(5);
      updateRouteMap();

      locationQueue = locationQueue.then(function () {
        var body = new URLSearchParams({
          csrf_token: driverActions.dataset.csrf,
          action: serverTracking ? "update" : "start",
          latitude: String(lat),
          longitude: String(lon)
        });
        return fetch(driverActions.dataset.locationUrl, {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "X-Requested-With": "XMLHttpRequest" },
          body: body.toString(),
          cache: "no-store"
        }).then(function (response) {
          return response.json().then(function (data) {
            if (!response.ok) throw new Error(data.error || "The server could not save this location.");
            serverTracking = true;
            $("#driver-trip-status").textContent = "In Progress";
            $("#driver-tracking-status").textContent = "In Progress";
            $("#driver-trip-started").textContent = displayTime(data.trip_started_at);
            $("#driver-last-updated").textContent = displayTime(data.last_updated);
            $("#driver-live-badge").classList.add("is-active");
            $("#driver-live-text").textContent = "LIVE – Location Sharing Active";
            driverStart.disabled = true;
            driverStop.disabled = false;
            setDriverMessage("Your live GPS location is being shared with Student and Admin dashboards.", false);
          });
        });
      }).catch(function (error) {
        setDriverMessage(error.message + " Check your connection and start tracking again.", true);
      });
      $("#driver-last-updated").textContent = displayTime(stamp);
    };
    driverStart.addEventListener("click", function () {
      if (!navigator.geolocation) {
        setDriverMessage("This browser does not support GPS location tracking.", true);
        return;
      }
      trackingRequested = true;
      driverStart.disabled = true;
      setDriverMessage("Requesting location permission…", false);
      trackingWatch = navigator.geolocation.watchPosition(function (position) {
        updateDriverLocation(position);
      }, function (error) {
        trackingRequested = false;
        if (trackingWatch !== null) navigator.geolocation.clearWatch(trackingWatch);
        trackingWatch = null;
        driverStart.disabled = false;
        if (error.code === error.PERMISSION_DENIED) {
          setDriverMessage("Location permission was denied. Allow location access in your browser to start tracking.", true);
        } else if (error.code === error.TIMEOUT) {
          setDriverMessage("GPS did not respond in time. Check your device location settings and try again.", true);
        } else {
          setDriverMessage("Your current location could not be determined. Try again when GPS is available.", true);
        }
      }, { enableHighAccuracy: true, maximumAge: 2000, timeout: 15000 });
    });
    driverStop.addEventListener("click", function () {
      trackingRequested = false;
      if (trackingWatch !== null) navigator.geolocation.clearWatch(trackingWatch);
      trackingWatch = null;
      driverStart.disabled = false;
      driverStop.disabled = true;
      if (!serverTracking) {
        $("#driver-trip-status").textContent = "Trip Ended";
        $("#driver-tracking-status").textContent = "Trip Ended";
        $("#driver-live-text").textContent = "Trip Ended";
        setDriverMessage("Trip ended. Location sharing has stopped.", false);
        return;
      }
      locationQueue = locationQueue.then(function () {
        var body = new URLSearchParams({ csrf_token: driverActions.dataset.csrf, action: "stop" });
        return fetch(driverActions.dataset.locationUrl, {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "X-Requested-With": "XMLHttpRequest" },
          body: body.toString(),
          cache: "no-store"
        }).then(function (response) {
          return response.json().then(function (data) {
            if (!response.ok) throw new Error(data.error || "The trip could not be stopped on the server.");
            serverTracking = false;
            driverLocation.dataset.live = "false";
            driverLocation.dataset.tripStatus = "Trip Ended";
            $("#driver-trip-status").textContent = "Trip Ended";
            $("#driver-tracking-status").textContent = "Trip Ended";
            $("#driver-live-badge").classList.remove("is-active");
            $("#driver-live-text").textContent = "Trip Ended";
            updateRouteMap();
            setDriverMessage(data.message, false);
          });
        });
      }).catch(function (error) {
        driverStop.disabled = false;
        setDriverMessage(error.message + " The GPS watch has stopped; retry Stop Trip when connected.", true);
      });
    });
  }

  // ---------- live map of all buses ----------
  var liveEl = $("#live-map");
  if (liveEl) {
    var markers = {}, liveMap = null, first = true;
    var initial = []; try { initial = JSON.parse($("#buses-data").textContent); } catch (e) {}
    var drawBuses = function (buses) {
      if (typeof L === "undefined") { liveEl.hidden = true; var n = $("#live-note-map"); if (n) n.hidden = false; return; }
      if (!liveMap) { liveMap = L.map("live-map").setView([18.53, 73.85], 11); L.tileLayer(TILES, { maxZoom: 19, attribution: ATTR }).addTo(liveMap); }
      buses.forEach(function (b) {
        if (b.lat === null || b.lon === null) { if (markers[b.route]) { liveMap.removeLayer(markers[b.route]); delete markers[b.route]; } return; }
        var sharingLabel = b.is_live && b.status === "current" ? "LIVE – Location Sharing Active" :
          (b.trip_status === "Trip Ended" ? "Trip Ended · last shared position" : "SIMULATED (" + b.label + ")");
        var html = "<strong>" + b.route + " · " + b.bus + "</strong><br>" + b.name + "<br>" + sharingLabel + (b.near ? "<br>Near " + b.near : "") + '<br><a href="/routes/' + b.route + '">Open route</a>';
        if (!markers[b.route]) markers[b.route] = L.marker([b.lat, b.lon], { icon: busIcon(b.status, true) }).addTo(liveMap).bindPopup(html);
        else { markers[b.route].setLatLng([b.lat, b.lon]).setIcon(busIcon(b.status, true)); markers[b.route].getPopup().setContent(html); }
      });
      if (first) { var pts = buses.filter(function (b) { return b.lat !== null; }).map(function (b) { return [b.lat, b.lon]; }); if (pts.length) liveMap.fitBounds(L.latLngBounds(pts).pad(0.1)); first = false; }
    };
    var updateList = function (buses) {
      var list = $("#bus-list"); if (!list) return;
      buses.forEach(function (b) {
        var row = list.querySelector('[data-route="' + b.route + '"]'); if (!row) return;
        row.querySelector(".badge").className = "badge badge-" + b.status;
        row.querySelector(".badge").innerHTML = '<i class="pulse"></i>' + b.label;
        row.querySelector(".muted").textContent = "🚌 " + b.bus + (b.near ? " · near " + b.near : "");
      });
    };
    drawBuses(initial);
    setInterval(function () {
      if (document.hidden) return;
      fetch("/api/buses", { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (d) {
        showNetworkProblem(false); stamp(); drawBuses(d.buses); updateList(d.buses);
      }).catch(function () { showNetworkProblem(true); });
    }, 5000);
    $$(".bus-row").forEach(function (row) {
      row.addEventListener("mouseenter", function () { var m = markers[row.dataset.route]; if (m) m.openPopup(); });
    });
  }

  // ---------- admin location status refresh ----------
  var adminLocations = $$("[data-admin-location]");
  if (adminLocations.length) {
    var refreshAdminLocations = function () {
      fetch("/api/buses", { cache: "no-store" }).then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      }).then(function (data) {
        data.buses.forEach(function (bus) {
          var cell = $('[data-admin-location="' + bus.route + '"]');
          if (!cell) return;
          var badge = cell.querySelector(".badge");
          var detail = cell.querySelector("[data-admin-location-detail]");
          if (badge) {
            badge.className = "badge badge-" + bus.status;
            badge.textContent = bus.is_live && bus.status === "current" ? "LIVE – Location Sharing Active" : bus.label;
          }
          if (detail) {
            detail.textContent = bus.lat === null ? bus.trip_status :
              bus.lat.toFixed(5) + ", " + bus.lon.toFixed(5) + (bus.is_live && bus.status === "current" ? " · LIVE" : "");
          }
        });
      }).catch(function () { showNetworkProblem(true); });
    };
    setInterval(function () { if (!document.hidden) refreshAdminLocations(); }, 5000);
    refreshAdminLocations();
  }

  // ---------- admin helpers ----------
  var reasonBox = $("#stop-reason");
  $$("form.needs-reason").forEach(function (form) {
    form.addEventListener("submit", function () {
      var hidden = form.querySelector("input[name=reason]"); if (hidden && reasonBox) hidden.value = reasonBox.value;
    });
  });
  $$("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) { if (!window.confirm(form.dataset.confirm)) e.preventDefault(); });
  });
})();

// Talks to the backend: JSON in and out, the server's message as the error text, and which trip this tab is on
// (?trip=<id> in the address, else the last trip planned in this tab). In agents mode the access code typed on the
// questionnaire is kept for this tab only and sent in the X-Access-Code header of POST requests, never in a URL.

(function () {
  const TRIP_KEY = "tp.tripId";
  const CODE_KEY = "tp.accessCode";

  function apiError(message, status, field) {
    const error = new Error(message);
    error.status = status;
    error.field = field || null;
    return error;
  }

  async function request(method, path, body) {
    const options = { method, headers: { Accept: "application/json" } };
    const code = method === "POST" ? accessCode() : "";
    if (code) options.headers["X-Access-Code"] = code;
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    let res;
    try {
      res = await fetch(path, options);
    } catch {
      throw apiError("The server can't be reached. Is it running?", 0);
    }
    let data = null;
    try { data = await res.json(); } catch { /* no JSON body */ }
    if (!res.ok) throw apiError((data && data.detail) || `The server answered ${res.status}.`, res.status, data && data.field);
    return data;
  }

  function accessCode() {
    try { return sessionStorage.getItem(CODE_KEY) || ""; } catch { return ""; }
  }

  function setAccessCode(code) {
    try {
      if (code) sessionStorage.setItem(CODE_KEY, code);
      else sessionStorage.removeItem(CODE_KEY);
    } catch { /* storage blocked: the code is not kept */ }
  }

  function rememberTrip(id) {
    try { sessionStorage.setItem(TRIP_KEY, id); } catch { /* storage blocked: the address still has the id */ }
  }

  function tripId() {
    const fromAddress = new URLSearchParams(window.location.search).get("trip");
    if (fromAddress) {
      rememberTrip(fromAddress);
      return fromAddress;
    }
    try { return sessionStorage.getItem(TRIP_KEY); } catch { return null; }
  }

  function tripPath(id, rest) {
    return `/api/trips/${encodeURIComponent(id)}${rest || ""}`;
  }

  window.TP = window.TP || {};
  window.TP.api = {
    get: (path) => request("GET", path),
    post: (path, body) => request("POST", path, body)
  };
  window.TP.tripId = tripId;
  window.TP.rememberTrip = rememberTrip;
  window.TP.accessCode = accessCode;
  window.TP.setAccessCode = setAccessCode;
  window.TP.tripPath = tripPath;
})();

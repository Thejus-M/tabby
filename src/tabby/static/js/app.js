// Tabby client. All bill state lives in the browser; the server only computes and (optionally) stores shares.

const STORAGE_KEY = "tabby:bill:v1";
const VPA_KEY = "tabby:vpa:v1";

const uid = (p = "") => p + Math.random().toString(36).slice(2, 9);

function rupees(paise) {
  return (paise / 100).toFixed(2);
}

function toPaise(value) {
  const n = Number(String(value).replace(/[,₹\s]/g, ""));
  return Number.isFinite(n) ? Math.round(n * 100) : 0;
}

const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" });
function money(paise) {
  return inr.format((paise || 0) / 100);
}

function store(key, value) {
  try {
    if (value === undefined) return JSON.parse(localStorage.getItem(key) || "null");
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    return null;
  }
}

async function api(path, body, opts = {}) {
  const res = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: body instanceof FormData || body === undefined ? {} : { "Content-Type": "application/json" },
    body: body instanceof FormData || body === undefined ? body : JSON.stringify(body),
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join("; ") : data.detail;
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return data;
}

// Bill <-> URL fragment, compressed with the browser's built-in deflate.
const b64url = {
  encode(buf) {
    let s = "";
    for (const b of new Uint8Array(buf)) s += String.fromCharCode(b);
    return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  },
  decode(str) {
    const s = atob(str.replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(s, (c) => c.charCodeAt(0));
  },
};

async function packFragment(obj) {
  const stream = new Blob([JSON.stringify(obj)]).stream().pipeThrough(new CompressionStream("deflate"));
  return b64url.encode(await new Response(stream).arrayBuffer());
}

async function unpackFragment(str) {
  const stream = new Blob([b64url.decode(str)]).stream().pipeThrough(new DecompressionStream("deflate"));
  return JSON.parse(await new Response(stream).text());
}

async function shareOrCopy(url, title) {
  if (navigator.share) {
    try {
      await navigator.share({ title, url });
      return "shared";
    } catch (e) {
      if (e.name === "AbortError") return "cancelled";
    }
  }
  try {
    await navigator.clipboard.writeText(url);
    return "copied";
  } catch {
    window.prompt("Copy this link", url);
    return "shown";
  }
}

function emptyBill() {
  return { title: "", people: [], items: [], charges: [], assignments: {}, payer_id: null };
}

const STEPS = ["items", "people", "assign", "settle"];

// Shrink big camera photos before upload (faster on mobile data); EXIF is dropped by the canvas.
async function shrinkPhoto(file, maxSide = 2400) {
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
    if (scale === 1 && file.size < 2_000_000) return file;
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.9));
    return blob || file;
  } catch {
    return file;
  }
}

function tabby() {
  return {
    step: "start",
    steps: STEPS,
    bill: store(STORAGE_KEY) || emptyBill(),
    vpa: store(VPA_KEY) || "",
    result: null,
    selected: [],
    expanded: null,
    newPerson: "",
    busy: false,
    error: "",
    toast: "",
    scanNote: "",
    scanFlags: {},
    scanWarnings: [],
    photoUrl: "",
    qr: null,
    joinCode: "",
    shareLink: "",

    money,
    rupees,
    toPaise,

    init() {
      if (this.bill.items.length) this.step = "items";
      let timer;
      this.$watch("bill", () => {
        store(STORAGE_KEY, this.bill);
        clearTimeout(timer);
        timer = setTimeout(() => this.recompute(), 150);
      });
      this.$watch("vpa", (v) => store(VPA_KEY, v.trim()));
      this.recompute();
    },

    flash(msg) {
      this.toast = msg;
      setTimeout(() => (this.toast = ""), 2200);
    },

    go(step) {
      this.error = "";
      this.step = step;
      window.scrollTo({ top: 0 });
    },

    stepIndex() {
      return STEPS.indexOf(this.step);
    },

    canGo(step) {
      if (step === "items") return true;
      if (step === "people") return this.bill.items.length > 0;
      return this.bill.items.length > 0 && this.bill.people.length > 0;
    },

    reset() {
      if (this.bill.items.length && !confirm("Start a new bill? The current one will be cleared.")) return;
      this.bill = emptyBill();
      this.selected = [];
      this.shareLink = "";
      this.clearScan();
      this.go("start");
    },

    async recompute() {
      try {
        this.result = await api("/api/split", this.bill);
      } catch (e) {
        this.result = null;
      }
    },

    // ---- scan / items
    clearScan() {
      if (this.photoUrl) URL.revokeObjectURL(this.photoUrl);
      this.photoUrl = "";
      this.scanNote = "";
      this.scanFlags = {};
      this.scanWarnings = [];
    },

    async scan(event) {
      const file = event.target.files?.[0];
      event.target.value = "";
      if (!file) return;
      this.clearScan();
      this.photoUrl = URL.createObjectURL(file); // stays in the browser, for checking rows against the photo
      const form = new FormData();
      form.append("image", await shrinkPhoto(file), "bill.jpg");
      this.busy = true;
      this.error = "";
      try {
        const res = await api("/api/scan", form);
        const keepPeople = this.bill.people;
        this.bill = { ...res.bill, people: keepPeople, assignments: {}, payer_id: this.bill.payer_id };
        this.scanFlags = res.flags || {};
        this.scanWarnings = res.warnings || [];
        this.scanNote =
          res.mismatch && Math.abs(res.mismatch) > 100
            ? `Lines add up to ${money(res.printed_total - res.mismatch)} but the bill says ${money(res.printed_total)}. Check the items below.`
            : "";
        this.go("items");
        this.flash(`Found ${res.bill.items.length} items`);
      } catch (e) {
        this.error = e.message + " You can type the items instead.";
      } finally {
        this.busy = false;
      }
    },

    unflag(id) {
      delete this.scanFlags[id];
    },

    manual() {
      if (!this.bill.items.length) this.addItem();
      this.go("items");
    },

    addItem() {
      this.bill.items.push({ id: uid("i"), name: "", quantity: 1, amount: 0, category: "food" });
      this.$nextTick(() => document.querySelector("[data-item-name]:last-of-type")?.focus());
    },

    removeItem(id) {
      this.unflag(id);
      this.bill.items = this.bill.items.filter((i) => i.id !== id);
      delete this.bill.assignments[id];
    },

    addCharge(kind = "tax") {
      const name = { tax: "GST", service: "Service charge", discount: "Discount", other: "Other" }[kind];
      const scope = kind === "tax" ? "food" : "all";
      this.bill.charges.push({ id: uid("c"), name, kind, amount: 0, scope, enabled: true });
    },

    setChargeAmount(charge, value) {
      const p = toPaise(value);
      charge.amount = charge.kind === "discount" ? -Math.abs(p) : p;
    },

    itemsTotal() {
      return this.bill.items.reduce((s, i) => s + (i.amount || 0), 0);
    },

    hasServiceCharge() {
      return this.bill.charges.some((c) => c.kind === "service" && c.enabled);
    },

    // ---- people
    addPerson() {
      const names = this.newPerson
        .split(",")
        .map((n) => n.trim())
        .filter(Boolean);
      for (const name of names) {
        const person = { id: uid("p"), name: name.slice(0, 60) };
        this.bill.people.push(person);
        if (!this.bill.payer_id) this.bill.payer_id = person.id;
      }
      this.newPerson = "";
    },

    removePerson(id) {
      this.bill.people = this.bill.people.filter((p) => p.id !== id);
      for (const shares of Object.values(this.bill.assignments)) delete shares[id];
      this.selected = this.selected.filter((s) => s !== id);
      if (this.bill.payer_id === id) this.bill.payer_id = this.bill.people[0]?.id ?? null;
    },

    personName(id) {
      return this.bill.people.find((p) => p.id === id)?.name ?? "";
    },

    initials(name) {
      return name
        .split(/\s+/)
        .map((w) => w[0])
        .join("")
        .slice(0, 2)
        .toUpperCase();
    },

    // ---- assign
    toggleSelected(id) {
      this.selected = this.selected.includes(id) ? this.selected.filter((s) => s !== id) : [...this.selected, id];
    },

    selectAll() {
      this.selected = this.selected.length === this.bill.people.length ? [] : this.bill.people.map((p) => p.id);
    },

    sharesOf(itemId) {
      return this.bill.assignments[itemId] || {};
    },

    owners(itemId) {
      return Object.entries(this.sharesOf(itemId)).filter(([, w]) => w > 0);
    },

    tapItem(item) {
      if (!this.selected.length) {
        this.expanded = this.expanded === item.id ? null : item.id;
        return;
      }
      const current = this.owners(item.id)
        .map(([id]) => id)
        .sort()
        .join();
      const wanted = [...this.selected].sort().join();
      if (current === wanted) {
        delete this.bill.assignments[item.id];
      } else {
        this.bill.assignments[item.id] = Object.fromEntries(this.selected.map((id) => [id, 1]));
      }
    },

    bump(itemId, personId, delta) {
      const shares = { ...this.sharesOf(itemId) };
      shares[personId] = Math.max(0, Math.min(99, (shares[personId] || 0) + delta));
      if (!shares[personId]) delete shares[personId];
      this.bill.assignments[itemId] = shares;
    },

    personTotal(id) {
      return this.result?.people.find((p) => p.person_id === id)?.total ?? 0;
    },

    progress() {
      return Math.round((this.result?.progress ?? 0) * 100);
    },

    // ---- settle
    payer() {
      return this.bill.people.find((p) => p.id === this.bill.payer_id);
    },

    async showQr(person) {
      if (!this.vpa.trim()) {
        this.error = "Add the payer's UPI ID on the People step to show QR codes.";
        return;
      }
      // `person` is a row from the split result: {person_id, name, total, ...}
      try {
        const res = await api("/api/qr", {
          vpa: this.vpa.trim(),
          name: this.payer()?.name || "Tabby",
          amount: person.total,
          note: `${this.bill.title || "Bill"} - ${person.name}`.slice(0, 80),
        });
        this.qr = { ...res, person: person.name, amount: person.total };
      } catch (e) {
        this.error = e.message;
      }
    },

    upiFragment() {
      const v = this.vpa.trim();
      if (!v) return "";
      return "#" + new URLSearchParams({ upi: v, pn: this.payer()?.name || "" }).toString();
    },

    async shareCode() {
      this.busy = true;
      try {
        const { code } = await api("/api/share", this.bill);
        this.shareLink = `${location.origin}/s/${code}${this.upiFragment()}`;
        this.flash(await this.shareResultText(await shareOrCopy(this.shareLink, "Our split")));
      } catch (e) {
        this.error = e.message;
      } finally {
        this.busy = false;
      }
    },

    async shareFragment() {
      const payload = { bill: this.bill, upi: this.vpa.trim(), pn: this.payer()?.name || "" };
      this.shareLink = `${location.origin}/s#d=${await packFragment(payload)}`;
      this.flash(await this.shareResultText(await shareOrCopy(this.shareLink, "Our split")));
    },

    shareResultText(outcome) {
      return { shared: "Shared", copied: "Link copied", shown: "Link ready", cancelled: "" }[outcome] || "";
    },

    join() {
      const code = this.joinCode.trim().toUpperCase();
      if (code.length === 6) location.href = `/s/${code}`;
    },
  };
}

function sharedView({ code }) {
  return {
    code,
    bill: null,
    result: null,
    vpa: "",
    payeeName: "",
    error: "",
    loading: true,
    qr: null,
    openId: null,
    money,

    async init() {
      const params = new URLSearchParams(location.hash.slice(1));
      try {
        if (this.code) {
          const res = await api(`/api/share/${encodeURIComponent(this.code)}`);
          this.bill = res.bill;
          this.result = res.split;
          this.vpa = params.get("upi") || "";
          this.payeeName = params.get("pn") || "";
        } else if (params.get("d")) {
          const data = await unpackFragment(params.get("d"));
          this.bill = data.bill;
          this.vpa = data.upi || "";
          this.payeeName = data.pn || "";
          this.result = await api("/api/split", this.bill);
        } else {
          throw new Error("This link is missing its split.");
        }
      } catch (e) {
        this.error = e.message || "Could not open this split.";
      } finally {
        this.loading = false;
      }
    },

    payerId() {
      return this.bill?.payer_id;
    },

    async showQr(person) {
      try {
        const res = await api("/api/qr", {
          vpa: this.vpa,
          name: this.payeeName || "Tabby",
          amount: person.total,
          note: `${this.bill.title || "Bill"} - ${person.name}`.slice(0, 80),
        });
        this.qr = { ...res, person: person.name, amount: person.total };
      } catch (e) {
        this.error = e.message;
      }
    },
  };
}

if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

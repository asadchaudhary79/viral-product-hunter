const EXPORT_COLUMNS = [
  "section",
  "niche",
  "rank",
  "product",
  "viral_score",
  "final_score",
  "retail_price",
  "currency",
  "source",
  "platform",
  "listing",
  "unit_price",
  "price_min",
  "price_max",
  "price_usd",
  "moq",
  "shipping",
  "rating",
  "reviews",
  "orders",
  "sales",
  "best_seller",
  "amazons_choice",
  "image",
  "product_link",
  "supplier_link",
  "supplier_evidence",
  "reason",
  "reasoning",
  "rejection",
  "ranking_method",
  "status",
  "message",
  "result_count",
  "status_code",
  "parse_status_code",
  "content_chars",
  "prices_found",
  "urls_found",
  "images_found",
  "captcha_or_robot_detected",
  "preview",
  "products_validated",
  "supplier_requests",
  "successful_requests",
  "failed_requests",
  "empty_requests",
];

const els = {
  form: document.getElementById("hunt-form"),
  niche: document.getElementById("niche"),
  audience: document.getElementById("audience"),
  problem: document.getElementById("problem"),
  briefSummary: document.getElementById("brief-summary"),
  briefResult: document.getElementById("brief-result"),
  huntBtn: document.getElementById("hunt-btn"),
  exportBtn: document.getElementById("export-btn"),
  status: document.getElementById("status"),
  statusLabel: document.getElementById("status-label"),
  statusDetail: document.getElementById("status-detail"),
  error: document.getElementById("error"),
  results: document.getElementById("results"),
  warnings: document.getElementById("warnings"),
  initialBody: document.getElementById("initial-body"),
  supplierMetrics: document.getElementById("supplier-metrics"),
  supplierList: document.getElementById("supplier-list"),
  finalBody: document.getElementById("final-body"),
  discoveryBody: document.getElementById("discovery-body"),
};

let latestResults = null;

function selectedChoice(group, multi = false) {
  const buttons = [...document.querySelectorAll(`.choice[data-group="${group}"]`)];
  const active = buttons.filter((button) => button.classList.contains("is-active"));
  if (multi) return active.map((button) => button.dataset.value).filter(Boolean);
  return active[0]?.dataset.value ?? "";
}

function collectBrief() {
  const priceRaw = selectedChoice("price");
  return {
    goal: selectedChoice("goal") || "dropshipping",
    audience: els.audience.value.trim(),
    price_max: priceRaw === "" ? null : Number(priceRaw),
    problem: els.problem.value.trim(),
    preferences: selectedChoice("prefer", true),
    avoid: selectedChoice("avoid", true),
  };
}

function priceSummary(priceMax) {
  if (priceMax === null || priceMax === undefined || priceMax === "") return "any price";
  return `under $${priceMax}`;
}

function updateBriefSummary() {
  const niche = els.niche.value.trim() || "your niche";
  const brief = collectBrief();
  els.briefSummary.innerHTML = `Hunting <strong>${esc(niche)}</strong> for <strong>${esc(brief.goal)}</strong>, ${esc(priceSummary(brief.price_max))}${brief.audience ? `, for <strong>${esc(brief.audience)}</strong>` : ""}${brief.problem ? `. Problem: <strong>${esc(brief.problem)}</strong>` : ""}.`;
}

document.querySelectorAll(".choice").forEach((button) => {
  button.addEventListener("click", () => {
    const multi = button.dataset.multi === "true";
    const group = button.dataset.group;
    if (multi) {
      button.classList.toggle("is-active");
    } else {
      document
        .querySelectorAll(`.choice[data-group="${group}"]`)
        .forEach((item) => item.classList.remove("is-active"));
      button.classList.add("is-active");
    }
    updateBriefSummary();
  });
});

["input", "change"].forEach((eventName) => {
  els.niche.addEventListener(eventName, updateBriefSummary);
  els.audience.addEventListener(eventName, updateBriefSummary);
  els.problem.addEventListener(eventName, updateBriefSummary);
});
updateBriefSummary();


function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function money(value, currency) {
  if (value === null || value === undefined || value === "") return "—";
  const amount = typeof value === "number" ? value.toFixed(2) : value;
  return currency ? `${amount} ${currency}` : String(amount);
}

function linkCell(url, label = "Open") {
  if (!url) return "—";
  return `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`;
}

function setStatus(label, detail) {
  els.status.classList.remove("is-hidden");
  els.statusLabel.textContent = label;
  els.statusDetail.textContent = detail;
}

function clearStatus() {
  els.status.classList.add("is-hidden");
}

function showError(message) {
  els.error.classList.remove("is-hidden");
  els.error.textContent = message;
}

function clearError() {
  els.error.classList.add("is-hidden");
  els.error.textContent = "";
}

function cell(value) {
  if (value === null || value === undefined || value === false) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function row(fields = {}) {
  return Object.fromEntries(EXPORT_COLUMNS.map((column) => [column, cell(fields[column])]));
}

function buildExportRows(results) {
  const niche = results.niche || "";
  const rows = [];

  for (const [index, product] of (results.initial_products || []).entries()) {
    const evidence = product.evidence || {};
    rows.push(
      row({
        section: "initial_ranking",
        niche,
        rank: index + 1,
        product: product.product,
        viral_score: product.viral_score,
        retail_price: product.price,
        currency: product.currency,
        source: product.source,
        rating: evidence.rating,
        reviews: evidence.reviews,
        sales: evidence.sales,
        best_seller: evidence.best_seller,
        amazons_choice: evidence.amazons_choice,
        image: product.image,
        product_link: product.url,
        reason: product.reason,
      }),
    );
  }

  const summary = results.supplier_summary || {};
  rows.push(
    row({
      section: "supplier_summary",
      niche,
      products_validated: summary.products_validated,
      supplier_requests: summary.total_supplier_requests,
      successful_requests: summary.successful_supplier_requests,
      failed_requests: summary.failed_supplier_requests,
      empty_requests: summary.empty_supplier_requests,
      message: JSON.stringify(summary.offers_by_platform || {}),
    }),
  );

  for (const productData of results.supplier_data || []) {
    const reference = productData.product_reference || {};
    for (const supplierResult of productData.supplier_results || []) {
      const status = supplierResult.error ? "error" : supplierResult.warning ? "warning" : "ok";
      const message = supplierResult.error || supplierResult.warning || "";
      const offers = supplierResult.offers || [];
      if (!offers.length) {
        rows.push(
          row({
            section: "supplier_offer",
            niche,
            rank: reference.rank,
            product: productData.product_name,
            platform: supplierResult.supplier_platform,
            source: supplierResult.source,
            status,
            message,
          }),
        );
      }
      for (const offer of offers) {
        const priceRange = offer.price_range || {};
        rows.push(
          row({
            section: "supplier_offer",
            niche,
            rank: reference.rank,
            product: productData.product_name,
            platform: offer.supplier_platform || supplierResult.supplier_platform,
            source: supplierResult.source,
            listing: offer.supplier_title,
            unit_price: offer.unit_price,
            price_min: priceRange.min,
            price_max: priceRange.max,
            price_usd: offer.price_usd,
            currency: offer.currency,
            moq: offer.min_order_quantity,
            shipping: offer.shipping_info,
            rating: offer.rating,
            reviews: offer.reviews,
            orders: offer.orders,
            supplier_link: offer.supplier_url,
            supplier_evidence: offer.supplier_evidence,
            status,
            message,
          }),
        );
      }
    }
  }

  for (const [index, product] of (results.final_products || []).entries()) {
    const offer = product.selected_supplier_offer || {};
    const priceRange = offer.price_range || {};
    rows.push(
      row({
        section: "final_ranking",
        niche,
        rank: index + 1,
        product: product.product,
        viral_score: product.viral_score,
        final_score: product.final_score,
        retail_price: product.price,
        currency: product.currency || offer.currency,
        source: product.source,
        platform: offer.supplier_platform,
        listing: offer.supplier_title,
        unit_price: offer.unit_price,
        price_min: priceRange.min,
        price_max: priceRange.max,
        price_usd: offer.price_usd,
        moq: offer.min_order_quantity,
        shipping: offer.shipping_info,
        rating: offer.rating,
        orders: offer.orders,
        reviews: offer.reviews,
        supplier_link: offer.supplier_url,
        reasoning: product.supplier_price_reasoning,
        rejection: product.rejection_reason,
        ranking_method: product.ranking_method,
      }),
    );
  }

  for (const source of results.discovery_summary || []) {
    rows.push(
      row({
        section: "discovery_source",
        niche,
        source: source.source,
        status: source.error ? "error" : "ok",
        message: source.error || "",
        result_count: source.result_count,
        status_code: source.status_code,
        parse_status_code: source.parse_status_code,
        content_chars: source.content_chars,
        prices_found: source.prices_found,
        urls_found: source.urls_found,
        images_found: source.images_found,
        captcha_or_robot_detected: source.captcha_or_robot_detected,
        preview: source.preview,
      }),
    );
  }

  for (const warning of results.ranking_warnings || []) {
    rows.push(row({ section: "warning", niche, status: "warning", message: warning }));
  }

  return rows;
}

function csvEscape(value) {
  const text = String(value ?? "");
  if (/[",\n]/.test(text)) return `"${text.replaceAll('"', '""')}"`;
  return text;
}

function rowsToCsv(rows) {
  const lines = [EXPORT_COLUMNS.join(",")];
  for (const item of rows) {
    lines.push(EXPORT_COLUMNS.map((column) => csvEscape(item[column])).join(","));
  }
  return `\ufeff${lines.join("\n")}`;
}

function exportFilename(niche) {
  const slug = (niche || "hunt").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "hunt";
  return `${slug}-viral-product-hunter.csv`;
}

function renderInitial(products) {
  els.initialBody.innerHTML = (products || [])
    .map(
      (product, index) => `
      <tr>
        <td>${index + 1}</td>
        <td>${esc(product.product)}</td>
        <td><span class="score">${esc(product.viral_score ?? "—")}</span></td>
        <td>${esc(money(product.price, product.currency))}</td>
        <td>${esc(product.source || "—")}</td>
        <td>${linkCell(product.url)}</td>
      </tr>`,
    )
    .join("") || `<tr><td colspan="6" class="muted">No products found.</td></tr>`;
}

function renderSupplierMetrics(summary = {}) {
  const items = [
    ["Products", summary.products_validated],
    ["Requests", summary.total_supplier_requests],
    ["Successful", summary.successful_supplier_requests],
    ["Failed", summary.failed_supplier_requests],
    ["Empty pages", summary.empty_supplier_requests],
  ];
  els.supplierMetrics.innerHTML = items
    .map(
      ([label, value]) => `
      <div class="metric">
        <strong>${esc(value ?? 0)}</strong>
        <span>${esc(label)}</span>
      </div>`,
    )
    .join("");
}

function offerPrice(offer) {
  if (offer.price_range) {
    return `${offer.price_range.min} - ${offer.price_range.max}`;
  }
  return offer.unit_price ?? "—";
}

function renderSuppliers(groups) {
  els.supplierList.innerHTML = (groups || [])
    .map((group) => {
      const notes = [];
      const offerRows = [];
      for (const result of group.supplier_results || []) {
        if (result.error) notes.push(`${result.supplier_platform}: ${result.error}`);
        else if (result.warning) notes.push(`${result.supplier_platform}: ${result.warning}`);
        for (const offer of result.offers || []) {
          offerRows.push(`
            <tr>
              <td>${esc(offer.supplier_platform)}</td>
              <td>${esc(offer.supplier_title)}</td>
              <td>${esc(offerPrice(offer))}</td>
              <td>${esc(offer.currency || "—")}</td>
              <td>${esc(offer.min_order_quantity || "—")}</td>
              <td>${esc(offer.shipping_info || "—")}</td>
              <td>${esc(offer.rating ?? "—")}</td>
              <td>${esc(offer.orders ?? "—")}</td>
              <td>${linkCell(offer.supplier_url)}</td>
            </tr>`);
        }
      }
      const body = offerRows.length
        ? `<div class="table-wrap"><table>
            <thead>
              <tr>
                <th>Platform</th><th>Listing</th><th>Price</th><th>Currency</th>
                <th>MOQ</th><th>Shipping</th><th>Rating</th><th>Orders</th><th></th>
              </tr>
            </thead>
            <tbody>${offerRows.join("")}</tbody>
          </table></div>`
        : `<p class="muted">No usable supplier offers found.</p>`;
      return `
        <details class="supplier-item">
          <summary>
            <span>${esc(group.product_name || "Unknown product")}</span>
            <span class="hint">${(group.supplier_results || []).length} sources</span>
          </summary>
          <div class="supplier-body">
            ${notes.map((note) => `<p class="note">${esc(note)}</p>`).join("")}
            ${body}
          </div>
        </details>`;
    })
    .join("") || `<p class="muted">No supplier data.</p>`;
}

function renderFinal(products) {
  els.finalBody.innerHTML = (products || [])
    .map((product, index) => {
      const offer = product.selected_supplier_offer || {};
      const notes = product.rejection_reason || product.supplier_price_reasoning || "—";
      return `
        <tr>
          <td>${index + 1}</td>
          <td>${esc(product.product)}</td>
          <td><span class="score">${esc(product.final_score ?? "—")}</span></td>
          <td>${esc(offer.supplier_platform || "—")}</td>
          <td>${esc(offer.price_usd ?? "—")}</td>
          <td>${esc(offer.min_order_quantity || "—")}</td>
          <td>${esc(notes)}</td>
          <td>${linkCell(offer.supplier_url)}</td>
        </tr>`;
    })
    .join("") || `<tr><td colspan="8" class="muted">No final ranking.</td></tr>`;
}

function renderDiscovery(summary) {
  els.discoveryBody.innerHTML = (summary || [])
    .map(
      (source) => `
      <tr>
        <td>${esc(source.source)}</td>
        <td>${esc(source.result_count ?? 0)}</td>
        <td>${esc(source.status_code ?? "—")}</td>
        <td>${esc(source.preview || "—")}</td>
        <td>${esc(source.error || "—")}</td>
      </tr>`,
    )
    .join("") || `<tr><td colspan="5" class="muted">No discovery summary.</td></tr>`;
}

function renderResults(results) {
  latestResults = results;
  const brief = results.brief || {};
  els.briefResult.innerHTML = `
    <strong>Brief used</strong><br />
    Niche: ${esc(results.niche || "—")} · Goal: ${esc(brief.goal || "dropshipping")} ·
    Budget: ${esc(priceSummary(brief.price_max))}
    ${brief.audience ? ` · Audience: ${esc(brief.audience)}` : ""}
    ${brief.problem ? `<br />Problem: ${esc(brief.problem)}` : ""}
    ${brief.preferences?.length ? `<br />Prefer: ${esc(brief.preferences.join(", "))}` : ""}
    ${brief.avoid?.length ? `<br />Avoid: ${esc(brief.avoid.join(", "))}` : ""}
  `;
  els.warnings.innerHTML = (results.ranking_warnings || [])
    .map((warning) => `<p class="warning">${esc(warning)}</p>`)
    .join("");
  renderInitial(results.initial_products);
  renderSupplierMetrics(results.supplier_summary);
  renderSuppliers(results.supplier_data);
  renderFinal(results.final_products);
  renderDiscovery(results.discovery_summary);
  els.results.classList.remove("is-hidden");
  els.exportBtn.classList.remove("is-hidden");
  els.results.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function postJson(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = payload.detail || JSON.stringify(payload);
    } catch {
      detail = await response.text();
    }
    throw new Error(`${response.status}: ${detail}`);
  }
  return response.json();
}

els.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const niche = els.niche.value.trim();
  if (!niche) return;
  const brief = collectBrief();

  clearError();
  els.results.classList.add("is-hidden");
  els.exportBtn.classList.add("is-hidden");
  latestResults = null;
  els.huntBtn.disabled = true;

  try {
    setStatus(
      "Discovering products for your brief…",
      `Searching sources for ${niche} · ${brief.goal} · ${priceSummary(brief.price_max)}`,
    );
    const discovery = await postJson("/discover", { niche, brief });
    setStatus(
      "Sourcing Alibaba and AliExpress offers…",
      `Initial ranking complete: ${(discovery.initial_products || []).length} candidates matched to your brief`,
    );
    const sourcing = await postJson("/source", {
      niche,
      brief,
      initial_products: discovery.initial_products || [],
    });
    const results = {
      ...discovery,
      ...sourcing,
      niche,
      brief: discovery.brief || brief,
      ranking_warnings: [
        ...(discovery.ranking_warnings || []),
        ...(sourcing.ranking_warnings || []),
      ],
    };
    setStatus("Hunt complete", "Results ranked against your brief");
    renderResults(results);
  } catch (error) {
    showError(
      `Failed to run the hunt: ${error.message}. Make sure the API is running at this same origin.`,
    );
  } finally {
    els.huntBtn.disabled = false;
    window.setTimeout(clearStatus, 1200);
  }
});

els.exportBtn.addEventListener("click", () => {
  if (!latestResults) return;
  const csv = rowsToCsv(buildExportRows(latestResults));
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = exportFilename(latestResults.niche);
  anchor.click();
  URL.revokeObjectURL(url);
});

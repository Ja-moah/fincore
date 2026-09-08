"use strict";

const state = {
  accessToken: sessionStorage.getItem("fincore_access"),
  refreshToken: sessionStorage.getItem("fincore_refresh"),
  username: sessionStorage.getItem("fincore_username"),
  account: null,
  lastTransfer: null,
};

const demoPasswords = {
  Admin: "admin123",
  Justice: "just123",
  Ama: "ama123",
  Kojo: "kojo123",
};

const elements = {
  loginView: document.querySelector("#login-view"),
  dashboardView: document.querySelector("#dashboard-view"),
  loginForm: document.querySelector("#login-form"),
  username: document.querySelector("#username"),
  password: document.querySelector("#password"),
  loginButton: document.querySelector("#login-button"),
  loginMessage: document.querySelector("#login-message"),
  logoutButton: document.querySelector("#logout-button"),
  refreshButton: document.querySelector("#refresh-button"),
  systemStatus: document.querySelector("#system-status"),
  systemStatusLabel: document.querySelector("#system-status-label"),
  displayName: document.querySelector("#display-name"),
  accountNumber: document.querySelector("#account-number"),
  accountStatus: document.querySelector("#account-status"),
  balanceValue: document.querySelector("#balance-value"),
  balanceUpdated: document.querySelector("#balance-updated"),
  transferForm: document.querySelector("#transfer-form"),
  recipient: document.querySelector("#recipient-account"),
  amount: document.querySelector("#amount"),
  idempotencyKey: document.querySelector("#idempotency-key"),
  newKeyButton: document.querySelector("#new-key-button"),
  sendButton: document.querySelector("#send-button"),
  retryButton: document.querySelector("#retry-button"),
  insufficientButton: document.querySelector("#insufficient-button"),
  transferResult: document.querySelector("#transfer-result"),
  resultIcon: document.querySelector("#result-icon"),
  resultTitle: document.querySelector("#result-title"),
  resultMessage: document.querySelector("#result-message"),
  resultTransactionId: document.querySelector("#result-transaction-id"),
  activityList: document.querySelector("#activity-list"),
  clearActivityButton: document.querySelector("#clear-activity-button"),
  transactionList: document.querySelector("#transaction-list"),
  historyCount: document.querySelector("#history-count"),
};

class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function generateIdempotencyKey(prefix = "dashboard") {
  const id = typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${id}`;
}

function setTokens(data, username) {
  state.accessToken = data.access;
  state.refreshToken = data.refresh;
  state.username = username;
  sessionStorage.setItem("fincore_access", data.access);
  sessionStorage.setItem("fincore_refresh", data.refresh);
  sessionStorage.setItem("fincore_username", username);
}

function clearTokens() {
  state.accessToken = null;
  state.refreshToken = null;
  state.username = null;
  state.account = null;
  state.lastTransfer = null;
  sessionStorage.removeItem("fincore_access");
  sessionStorage.removeItem("fincore_refresh");
  sessionStorage.removeItem("fincore_username");
}

function showLogin(message = "") {
  elements.loginView.hidden = false;
  elements.dashboardView.hidden = true;
  elements.logoutButton.hidden = true;
  elements.loginMessage.textContent = message;
}

function showDashboard() {
  elements.loginView.hidden = true;
  elements.dashboardView.hidden = false;
  elements.logoutButton.hidden = false;
  elements.displayName.textContent = (state.username || "account holder").replace("demo_", "");
}

async function readResponse(response) {
  let body = {};
  try {
    body = await response.json();
  } catch (_error) {
    body = {};
  }
  if (!response.ok) {
    const detail = body.error || {};
    throw new ApiError(response.status, detail.code || "REQUEST_FAILED", detail.message || body.detail || "The request could not be completed.");
  }
  return body;
}

async function refreshAccessToken() {
  if (!state.refreshToken) return false;
  const response = await fetch("/api/v1/auth/token/refresh/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh: state.refreshToken }),
  });
  if (!response.ok) return false;
  const data = await response.json();
  state.accessToken = data.access;
  sessionStorage.setItem("fincore_access", data.access);
  return true;
}

async function apiRequest(path, options = {}, allowRefresh = true) {
  const headers = new Headers(options.headers || {});
  if (options.body) headers.set("Content-Type", "application/json");
  if (state.accessToken) headers.set("Authorization", `Bearer ${state.accessToken}`);
  headers.set("X-Request-ID", crypto.randomUUID());
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401 && allowRefresh && await refreshAccessToken()) {
    return apiRequest(path, options, false);
  }
  return readResponse(response);
}

function formatMoney(value, currency = "GHS") {
  return new Intl.NumberFormat("en-GH", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format(Number(value));
}

function formatDate(value) {
  return new Intl.DateTimeFormat("en-GH", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function addActivity(title, detail, tone = "info") {
  const empty = elements.activityList.querySelector(".activity-empty");
  if (empty) empty.remove();
  const item = document.createElement("li");
  item.className = tone;
  const strong = document.createElement("strong");
  strong.textContent = title;
  const description = document.createElement("span");
  description.textContent = detail;
  const time = document.createElement("time");
  time.dateTime = new Date().toISOString();
  time.textContent = new Intl.DateTimeFormat("en-GH", { timeStyle: "medium" }).format(new Date());
  item.append(strong, description, time);
  elements.activityList.prepend(item);
}

function renderTransactions(data) {
  const transactions = Array.isArray(data) ? data : (data.results || []);
  elements.transactionList.replaceChildren();
  elements.historyCount.textContent = `${transactions.length} ${transactions.length === 1 ? "record" : "records"}`;

  if (!transactions.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 5;
    cell.className = "empty-cell";
    cell.textContent = "No transaction history yet.";
    row.append(cell);
    elements.transactionList.append(row);
    return;
  }

  for (const transaction of transactions) {
    const outgoing = transaction.sender_account === state.account.account_number;
    const row = document.createElement("tr");

    const idCell = document.createElement("td");
    const id = document.createElement("span");
    id.className = "transaction-id";
    id.title = transaction.id;
    id.textContent = transaction.id;
    const direction = document.createElement("span");
    direction.className = "direction-label";
    direction.textContent = outgoing ? "Sent" : "Received";
    idCell.append(id, direction);

    const counterparty = document.createElement("td");
    counterparty.textContent = outgoing ? transaction.recipient_account : transaction.sender_account;

    const statusCell = document.createElement("td");
    const status = document.createElement("span");
    status.className = "transaction-status";
    status.textContent = transaction.status;
    statusCell.append(status);

    const date = document.createElement("td");
    date.textContent = formatDate(transaction.created_at);

    const amount = document.createElement("td");
    amount.className = "amount-column amount-value " + (outgoing ? "debit" : "credit");
    amount.textContent = `${outgoing ? "−" : "+"}${formatMoney(transaction.amount, transaction.currency)}`;

    row.append(idCell, counterparty, statusCell, date, amount);
    elements.transactionList.append(row);
  }
}

async function loadDashboard(logRefresh = false) {
  elements.refreshButton.disabled = true;
  try {
    const [account, balance, transactions] = await Promise.all([
      apiRequest("/api/v1/accounts/me/"),
      apiRequest("/api/v1/accounts/me/balance/"),
      apiRequest("/api/v1/transactions/"),
    ]);
    state.account = account;
    elements.accountNumber.textContent = account.account_number;
    elements.accountStatus.textContent = account.status;
    elements.balanceValue.textContent = formatMoney(balance.balance, balance.currency);
    elements.balanceUpdated.textContent = `Updated ${new Intl.DateTimeFormat("en-GH", { timeStyle: "short" }).format(new Date())}`;
    renderTransactions(transactions);
    if (logRefresh) addActivity("Dashboard refreshed", "Balance and transaction history were read from the API.", "success");
  } catch (error) {
    if (error.status === 401) {
      clearTokens();
      showLogin("Your session expired. Please sign in again.");
      return;
    }
    addActivity("Could not refresh dashboard", error.message, "error");
  } finally {
    elements.refreshButton.disabled = false;
  }
}

async function checkHealth() {
  try {
    const response = await fetch("/health/");
    const data = await response.json();
    const healthy = response.ok && data.status === "healthy";
    elements.systemStatus.className = `system-status ${healthy ? "healthy" : "unhealthy"}`;
    elements.systemStatusLabel.textContent = healthy ? "System healthy" : "System unavailable";
  } catch (_error) {
    elements.systemStatus.className = "system-status unhealthy";
    elements.systemStatusLabel.textContent = "System unavailable";
  }
}

elements.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  elements.loginMessage.textContent = "";
  elements.loginButton.disabled = true;
  elements.loginButton.textContent = "Signing in…";
  const username = new FormData(elements.loginForm).get("username");
  const password = new FormData(elements.loginForm).get("password");
  try {
    const response = await fetch("/api/v1/auth/token/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await readResponse(response);
    setTokens(data, username);
    showDashboard();
    addActivity("Authenticated", `${username} received a short-lived access token.`, "success");
    await loadDashboard();
  } catch (error) {
    elements.loginMessage.textContent = error.status === 401 ? "The username or password is incorrect." : error.message;
  } finally {
    elements.loginButton.disabled = false;
    elements.loginButton.textContent = "Sign in securely";
  }
});

elements.username.addEventListener("change", () => {
  elements.password.value = demoPasswords[elements.username.value] || "";
});

elements.logoutButton.addEventListener("click", () => {
  clearTokens();
  elements.activityList.replaceChildren();
  const item = document.createElement("li");
  item.className = "activity-empty";
  item.textContent = "Actions and API outcomes will appear here.";
  elements.activityList.append(item);
  showLogin();
});

elements.refreshButton.addEventListener("click", () => loadDashboard(true));

elements.newKeyButton.addEventListener("click", () => {
  elements.idempotencyKey.value = generateIdempotencyKey();
  elements.retryButton.hidden = true;
});

elements.insufficientButton.addEventListener("click", () => {
  if (!elements.recipient.value) {
    elements.recipient.value = state.account?.account_number === "DEMO-GHS-AMA" ? "DEMO-GHS-KOJO" : "DEMO-GHS-AMA";
  }
  elements.amount.value = "999999.00";
  elements.idempotencyKey.value = generateIdempotencyKey("insufficient");
  elements.retryButton.hidden = true;
  elements.amount.focus();
  addActivity("Failure example loaded", "Submit this request to prove insufficient funds do not mutate the ledger.");
});

elements.retryButton.addEventListener("click", () => elements.transferForm.requestSubmit());

elements.transferForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    recipient_account: elements.recipient.value.trim(),
    amount: Number(elements.amount.value).toFixed(2),
    currency: "GHS",
  };
  const key = elements.idempotencyKey.value.trim();
  const isRetry = state.lastTransfer?.key === key
    && JSON.stringify(state.lastTransfer.payload) === JSON.stringify(payload);

  elements.sendButton.disabled = true;
  elements.retryButton.disabled = true;
  elements.sendButton.textContent = isRetry ? "Retrying safely…" : "Sending…";
  elements.transferResult.hidden = true;
  addActivity(isRetry ? "Retry sent" : "Transfer requested", `${formatMoney(payload.amount)} to ${payload.recipient_account}.`);

  try {
    const result = await apiRequest("/api/v1/transfers/", {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify(payload),
    });
    const replayConfirmed = isRetry && state.lastTransfer.result.id === result.id;
    elements.transferResult.className = "transfer-result";
    elements.resultIcon.textContent = "✓";
    elements.resultTitle.textContent = replayConfirmed ? "Safe retry confirmed" : "Transfer succeeded";
    elements.resultMessage.textContent = replayConfirmed
      ? "The API returned the original transaction. No second movement was created."
      : `${formatMoney(result.amount, result.currency)} was posted as a balanced debit and credit.`;
    elements.resultTransactionId.textContent = result.id;
    elements.transferResult.hidden = false;
    addActivity(
      replayConfirmed ? "No duplicate movement" : "Transfer committed",
      replayConfirmed ? `Original transaction ${result.id} was replayed.` : `Transaction ${result.id} succeeded atomically.`,
      "success",
    );
    state.lastTransfer = { key, payload, result };
    elements.retryButton.hidden = false;
    await loadDashboard();
  } catch (error) {
    elements.transferResult.className = "transfer-result error";
    elements.resultIcon.textContent = "!";
    elements.resultTitle.textContent = error.code.replaceAll("_", " ");
    elements.resultMessage.textContent = error.message;
    elements.resultTransactionId.textContent = `HTTP ${error.status}`;
    elements.transferResult.hidden = false;
    elements.retryButton.hidden = true;
    addActivity(`Request rejected · ${error.code}`, error.message, "error");
    await loadDashboard();
  } finally {
    elements.sendButton.disabled = false;
    elements.retryButton.disabled = false;
    elements.sendButton.textContent = "Send money";
  }
});

elements.clearActivityButton.addEventListener("click", () => {
  elements.activityList.replaceChildren();
  const item = document.createElement("li");
  item.className = "activity-empty";
  item.textContent = "Actions and API outcomes will appear here.";
  elements.activityList.append(item);
});

elements.idempotencyKey.value = generateIdempotencyKey();
checkHealth();

if (state.accessToken) {
  showDashboard();
  loadDashboard();
} else {
  showLogin();
}

"use strict";

const portal = document.getElementById("portal");
const loginPanel = document.getElementById("login-panel");
const dashboardPanel = document.getElementById("dashboard-panel");
const logoutButton = document.getElementById("logout");
const message = document.getElementById("message");
const accessKey = "attendease-access-token";
const refreshKey = "attendease-refresh-token";

function showMessage(text, danger = false) {
  message.textContent = text;
  message.className = `alert alert-${danger ? "danger" : "info"}`;
}

function clearMessage() {
  message.textContent = "";
  message.className = "alert d-none";
}

function showLogin() {
  loginPanel.classList.remove("d-none");
  dashboardPanel.classList.add("d-none");
  logoutButton.classList.add("d-none");
}

function showDashboard() {
  loginPanel.classList.add("d-none");
  dashboardPanel.classList.remove("d-none");
  logoutButton.classList.remove("d-none");
}

function clearTokens() {
  sessionStorage.removeItem(accessKey);
  sessionStorage.removeItem(refreshKey);
}

async function refreshAccess() {
  const refresh = sessionStorage.getItem(refreshKey);
  if (!refresh) return false;
  const response = await fetch(portal.dataset.refreshUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh }),
  });
  if (!response.ok) return false;
  const data = await response.json();
  sessionStorage.setItem(accessKey, data.access);
  return true;
}

async function apiGet(url) {
  let response = await fetch(url, {
    headers: { Authorization: `Bearer ${sessionStorage.getItem(accessKey)}` },
  });
  if (response.status === 401 && await refreshAccess()) {
    response = await fetch(url, {
      headers: { Authorization: `Bearer ${sessionStorage.getItem(accessKey)}` },
    });
  }
  if (!response.ok) throw new Error(response.status === 401 ? "Please sign in again." : "Could not load attendance data.");
  return response.json();
}

function renderCourses(courses) {
  const container = document.getElementById("course-cards");
  container.replaceChildren();
  if (!courses.length) {
    const empty = document.createElement("p");
    empty.className = "text-muted";
    empty.textContent = "You are not enrolled in any active courses.";
    container.append(empty);
    return;
  }
  for (const course of courses) {
    const column = document.createElement("div");
    column.className = "col";
    const card = document.createElement("div");
    card.className = "card h-100 shadow-sm";
    const body = document.createElement("div");
    body.className = "card-body";
    const heading = document.createElement("h3");
    heading.className = "h5";
    heading.textContent = `${course.course_code} — ${course.course_title}`;
    const percentage = document.createElement("p");
    percentage.className = "display-6 mb-1";
    percentage.textContent = `${course.attendance_percentage}%`;
    const badge = document.createElement("span");
    badge.className = `badge ${course.below_threshold ? "bg-danger" : "bg-success"}`;
    badge.textContent = course.below_threshold ? "Below threshold" : "On track";
    const threshold = document.createElement("p");
    threshold.className = "text-muted small mt-2 mb-0";
    threshold.textContent = `Required: ${course.threshold}%`;
    body.append(heading, percentage, badge, threshold);
    card.append(body);
    column.append(card);
    container.append(column);
  }
}

function renderHistory(history) {
  const body = document.getElementById("history-rows");
  body.replaceChildren();
  document.getElementById("empty-history").classList.toggle("d-none", history.length > 0);
  for (const item of history) {
    const row = document.createElement("tr");
    for (const value of [item.date, `${item.course_code} — ${item.course_title}`, item.section_code]) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    const statusCell = document.createElement("td");
    statusCell.textContent = item.status === "present" ? "Present" : "Absent";
    row.append(statusCell);
    body.append(row);
  }
}

async function loadHistory() {
  const params = new URLSearchParams();
  const from = document.getElementById("from-date").value;
  const to = document.getElementById("to-date").value;
  if (from && to && from > to) throw new Error("From date must be on or before To date.");
  if (from) params.set("from", from);
  if (to) params.set("to", to);
  const query = params.toString();
  const data = await apiGet(`${portal.dataset.historyUrl}${query ? `?${query}` : ""}`);
  renderHistory(data.history);
}

async function loadDashboard() {
  try {
    const data = await apiGet(portal.dataset.dashboardUrl);
    renderCourses(data.courses);
    await loadHistory();
    showDashboard();
    clearMessage();
  } catch (error) {
    clearTokens();
    showLogin();
    showMessage(error.message, true);
  }
}

document.getElementById("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  clearMessage();
  const form = event.currentTarget;
  const email = form.elements.namedItem("email");
  const password = form.elements.namedItem("password");
  try {
    const response = await fetch(portal.dataset.loginUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: email.value, password: password.value }),
    });
    if (!response.ok) throw new Error("Sign-in failed. Check your credentials or try later.");
    const data = await response.json();
    sessionStorage.setItem(accessKey, data.access);
    sessionStorage.setItem(refreshKey, data.refresh);
    password.value = "";
    await loadDashboard();
  } catch (error) {
    showMessage(error.message, true);
  }
});

document.getElementById("date-filter").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await loadHistory();
    clearMessage();
  } catch (error) {
    showMessage(error.message, true);
  }
});

logoutButton.addEventListener("click", async () => {
  try {
    await fetch(portal.dataset.logoutUrl, {
      method: "POST",
      headers: { Authorization: `Bearer ${sessionStorage.getItem(accessKey)}` },
    });
  } catch {
    // Local sign-out still clears browser tokens if the server is unreachable.
  } finally {
    clearTokens();
    showLogin();
    showMessage("You have signed out.");
  }
});

if (sessionStorage.getItem(accessKey)) loadDashboard();
else showLogin();

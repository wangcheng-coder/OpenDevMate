document.getElementById("refresh").addEventListener("click", () => run(() => api("/api/dashboard")));
document.getElementById("create").addEventListener("click", () => run(() => api("/api/projects", {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({
    name: document.getElementById("name").value,
    description: document.getElementById("description").value
  })
})));
document.getElementById("projects").addEventListener("click", () => run(() => api("/api/projects")));
document.getElementById("tasks").addEventListener("click", () => run(() => api("/api/projects/" + encodeURIComponent(document.getElementById("project").value) + "/tasks")));
document.getElementById("add-task").addEventListener("click", () => run(() => api("/api/projects/" + encodeURIComponent(document.getElementById("project").value) + "/tasks", {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({title: document.getElementById("title").value, description: ""})
})));

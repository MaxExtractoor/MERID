import client from "./client";

export async function login(email: string, password: string) {
  const res = await client.post("/auth/login", { email, password });
  // if token in body:
  const token = res.data.access_token;
  if (token) {
    localStorage.setItem("merid-access", token);
    client.defaults.headers.common["Authorization"] = `Bearer ${token}`;
  }
}

export function initAuth() {
  const token = localStorage.getItem("merid-access");
  if (token) {
    client.defaults.headers.common["Authorization"] = `Bearer ${token}`;
  }
}

// Call this on app startup
initAuth();

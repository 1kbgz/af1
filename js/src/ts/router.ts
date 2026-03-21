/** af1 — Simple hash-based router. */

type RouteHandler = (
  container: HTMLElement,
  ...params: string[]
) => Promise<void>;

const routes: Array<{ pattern: RegExp; handler: RouteHandler }> = [];

export function registerRoute(pattern: RegExp, handler: RouteHandler): void {
  routes.push({ pattern, handler });
}

export function navigateTo(path: string): void {
  window.location.hash = path;
}

export async function handleRoute(): Promise<void> {
  const hash = window.location.hash.replace(/^#/, "") || "/";
  const container = document.getElementById("view-container");
  if (!container) return;

  for (const route of routes) {
    const match = hash.match(route.pattern);
    if (match) {
      await route.handler(container, ...match.slice(1));
      return;
    }
  }

  // Fallback: go home
  navigateTo("/");
}

import { Link, Outlet, useLocation } from "react-router-dom";
import { Bot, Clapperboard, FolderKanban, ImageIcon, PanelLeftClose, PanelLeftOpen, Sparkles } from "lucide-react";
import { useState } from "react";

const APP_NAV_COLLAPSED_STORAGE_KEY = "storyforge.appNavCollapsed";

export function AppShell() {
  const location = useLocation();
  const [navCollapsed, setNavCollapsed] = useState(() => readStoredNavCollapsed());
  const isLanding = location.pathname === "/";
  const isImageRoute = location.pathname.startsWith("/console/images") || location.pathname.startsWith("/console/image-projects");
  const isAgentRoute = location.pathname.startsWith("/console/agent");
  const landingNavItems = [
    { href: "#create", label: "开始创作" },
    { href: "#workflow", label: "生产流程" },
    { href: "/console", label: "项目库" }
  ];

  return (
    <div className={isLanding ? "app-shell landing-shell" : navCollapsed ? "app-shell workbench-shell side-nav-collapsed" : "app-shell workbench-shell"}>
      {isLanding ? (
        <header className="app-topbar landing-topbar">
          <Link className="brand-lockup" to="/">
            <span className="brand-mark" aria-hidden="true">
              <Sparkles size={20} />
            </span>
            <span>
              <strong>StoryForge</strong>
              <em>Studio OS</em>
            </span>
          </Link>
          <nav className="top-nav landing-nav" aria-label="StoryForge 主导航">
            {landingNavItems.map((item) =>
              item.href.startsWith("#") ? (
                <a key={item.href} className="top-nav-link" href={item.href}>
                  <span>{item.label}</span>
                </a>
              ) : (
                <Link key={item.href} className="top-nav-link" to={item.href}>
                  <span>{item.label}</span>
                </Link>
              )
            )}
          </nav>
          <Link className="landing-nav-cta" to="/console/new">
            开始创作
          </Link>
        </header>
      ) : null}
      {!isLanding ? (
        <aside className="app-side-nav" aria-label="StoryForge 应用导航">
          <Link className="side-brand" to="/" aria-label="返回首页">
            <span className="brand-mark" aria-hidden="true">
              <Sparkles size={20} />
            </span>
            <span className="side-label">
              <strong>StoryForge</strong>
              <em>首页</em>
            </span>
          </Link>

          <button
            className="side-collapse-button"
            type="button"
            aria-label={navCollapsed ? "展开侧边栏" : "收起侧边栏"}
            onClick={() => {
              setNavCollapsed((current) => {
                const next = !current;
                writeStoredNavCollapsed(next);
                return next;
              });
            }}
          >
            {navCollapsed ? <PanelLeftOpen size={16} aria-hidden="true" /> : <PanelLeftClose size={16} aria-hidden="true" />}
            <span className="side-label">{navCollapsed ? "展开" : "收起"}</span>
          </button>

          <nav className="side-nav-primary" aria-label="主导航">
            <Link className={location.pathname === "/console" ? "side-nav-link active" : "side-nav-link"} to="/console">
              <FolderKanban size={18} aria-hidden="true" />
              <span className="side-label">项目库</span>
            </Link>
            <Link className={location.pathname === "/console/new" ? "side-nav-link active" : "side-nav-link"} to="/console/new">
              <Clapperboard size={18} aria-hidden="true" />
              <span className="side-label">小说转视频</span>
            </Link>
            <Link className={isAgentRoute ? "side-nav-link active" : "side-nav-link"} to="/console/agent">
              <Bot size={18} aria-hidden="true" />
              <span className="side-label">Agent 创作</span>
            </Link>
            <Link
              className={isImageRoute ? "side-nav-link active" : "side-nav-link"}
              to="/console/images"
            >
              <ImageIcon size={18} aria-hidden="true" />
              <span className="side-label">生图</span>
            </Link>
          </nav>
        </aside>
      ) : null}
      <div className="workspace-frame">
        <main className="main-canvas">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function readStoredNavCollapsed(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(APP_NAV_COLLAPSED_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

function writeStoredNavCollapsed(collapsed: boolean) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(APP_NAV_COLLAPSED_STORAGE_KEY, collapsed ? "true" : "false");
  } catch {
    // Ignore storage failures.
  }
}

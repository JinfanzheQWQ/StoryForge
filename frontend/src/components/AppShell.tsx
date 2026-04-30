import { Link, Outlet, useLocation } from "react-router-dom";
import { Clapperboard, FolderKanban, ImageIcon, Sparkles } from "lucide-react";

export function AppShell() {
  const location = useLocation();
  const isLanding = location.pathname === "/";
  const isImageRoute = location.pathname.startsWith("/console/images") || location.pathname.startsWith("/console/image-projects");
  const landingNavItems = [
    { href: "#create", label: "开始创作" },
    { href: "#workflow", label: "生产流程" },
    { href: "/console", label: "项目库" }
  ];

  return (
    <div className={isLanding ? "app-shell landing-shell" : "app-shell workbench-shell"}>
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
            <span>
              <strong>StoryForge</strong>
              <em>首页</em>
            </span>
          </Link>

          <nav className="side-nav-primary" aria-label="主导航">
            <Link className={location.pathname === "/console" ? "side-nav-link active" : "side-nav-link"} to="/console">
              <FolderKanban size={18} aria-hidden="true" />
              <span>项目库</span>
            </Link>
            <Link className={location.pathname === "/console/new" ? "side-nav-link active" : "side-nav-link"} to="/console/new">
              <Clapperboard size={18} aria-hidden="true" />
              <span>小说转视频</span>
            </Link>
            <Link
              className={isImageRoute ? "side-nav-link active" : "side-nav-link"}
              to="/console/images"
            >
              <ImageIcon size={18} aria-hidden="true" />
              <span>生图</span>
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

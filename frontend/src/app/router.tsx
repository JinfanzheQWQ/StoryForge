import { lazy, Suspense } from "react";
import type { ReactElement } from "react";
import { createBrowserRouter, Navigate } from "react-router-dom";
import { AppShell } from "../components/AppShell";

const LandingPage = lazy(() => import("../features/landing/LandingPage").then((module) => ({ default: module.LandingPage })));
const ImageProjectPage = lazy(() => import("../features/images/ImageProjectPage").then((module) => ({ default: module.ImageProjectPage })));
const ImageStudioPage = lazy(() => import("../features/images/ImageStudioPage").then((module) => ({ default: module.ImageStudioPage })));
const NewProjectPage = lazy(() => import("../features/projects/NewProjectPage").then((module) => ({ default: module.NewProjectPage })));
const ProjectListPage = lazy(() => import("../features/projects/ProjectListPage").then((module) => ({ default: module.ProjectListPage })));
const ProjectWorkspacePage = lazy(() =>
  import("../features/workspace/ProjectWorkspacePage").then((module) => ({ default: module.ProjectWorkspacePage }))
);

function lazyRoute(element: ReactElement) {
  return <Suspense fallback={<div className="route-loading" role="status">正在加载...</div>}>{element}</Suspense>;
}

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: lazyRoute(<LandingPage />) },
      { path: "console", element: lazyRoute(<ProjectListPage />) },
      { path: "console/new", element: lazyRoute(<NewProjectPage />) },
      { path: "console/images", element: lazyRoute(<ImageStudioPage />) },
      { path: "console/images/text-to-image", element: <Navigate to="/console/images" replace /> },
      { path: "console/images/image-to-image", element: <Navigate to="/console/images" replace /> },
      { path: "console/image-projects/:projectId", element: lazyRoute(<ImageProjectPage />) },
      { path: "console/projects/:projectId", element: lazyRoute(<ProjectWorkspacePage />) },
      { path: "console/projects/:projectId/run/:taskId", element: lazyRoute(<ProjectWorkspacePage />) },
      { path: "projects/new", element: <Navigate to="/console/new" replace /> },
      { path: "projects/:projectId", element: lazyRoute(<ProjectWorkspacePage />) },
      { path: "projects/:projectId/run/:taskId", element: lazyRoute(<ProjectWorkspacePage />) },
      { path: "*", element: <Navigate to="/" replace /> }
    ]
  }
]);

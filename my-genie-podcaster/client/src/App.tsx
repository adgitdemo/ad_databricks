import { createBrowserRouter, RouterProvider, NavLink, Outlet } from 'react-router';
import { Sparkles } from 'lucide-react';
import { PodcastListPage } from '@/pages/PodcastListPage';
import { NewPodcastPage } from '@/pages/NewPodcastPage';
import { PodcastDetailPage } from '@/pages/PodcastDetailPage';

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
    isActive
      ? 'bg-primary text-primary-foreground'
      : 'text-muted-foreground hover:bg-muted hover:text-foreground'
  }`;

function Layout() {
  return (
    <div className="min-h-screen bg-background flex flex-col">
      <header className="border-b px-4 md:px-6 py-3 flex items-center gap-2 sm:gap-4">
        <NavLink to="/" className="flex min-w-0 items-center gap-2 text-foreground">
          <img src="/favicon.svg" alt="" className="h-8 w-8 shrink-0" />
          <h1 className="truncate text-base font-semibold sm:text-lg">My Genie Podcaster</h1>
        </NavLink>
        <nav className="ml-auto flex shrink-0 gap-1">
          <NavLink to="/" end className={navLinkClass}>
            Podcasts
          </NavLink>
        </nav>
      </header>

      <main className="flex-1 p-4 md:p-6">
        <Outlet />
      </main>

      <footer className="border-t px-4 py-3">
        <p className="flex items-center justify-center gap-1.5 text-xs text-muted-foreground">
          <Sparkles className="h-3.5 w-3.5 text-primary" /> Powered by Databricks Genie
        </p>
      </footer>
    </div>
  );
}

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: '/', element: <PodcastListPage /> },
      { path: '/new', element: <NewPodcastPage /> },
      { path: '/podcast/:id', element: <PodcastDetailPage /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}

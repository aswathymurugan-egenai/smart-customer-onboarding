import { ThemeToggle } from "@/components/theme-toggle";

import { RegistrationWorkspace } from "./registration-workspace";

export default function HomePage() {
  return (
    <>
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-primary px-4 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:left-4 focus:top-4"
      >
        Skip to the signup form
      </a>
      <div className="mx-auto flex min-h-screen w-full max-w-6xl flex-col gap-6 px-4 py-6 md:px-6">
        <header className="flex items-center justify-between gap-4">
          <h1 className="text-2xl font-semibold tracking-tight">Customer signup</h1>
          <ThemeToggle />
        </header>
        <main id="main" tabIndex={-1} className="outline-none">
          <RegistrationWorkspace />
        </main>
      </div>
    </>
  );
}

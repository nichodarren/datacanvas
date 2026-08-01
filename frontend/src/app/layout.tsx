import type { Metadata } from "next";
import "./globals.css";
import { THEME_BOOTSTRAP } from "@/lib/theme";

export const metadata: Metadata = {
  title: "DataCanvas",
  description: "Deterministic AI-assisted data analysis",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // `suppressHydrationWarning` because the script below writes `data-theme`
    // onto this element before React ever sees it, so the server's markup and
    // the client's DOM legitimately differ by one attribute. Scoped to this
    // element only — it is not a blanket permission for the tree beneath it.
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Runs before the first paint. Without it, a person who chose dark on
            a light machine gets a white flash on every page load while React
            mounts and corrects the ground. See `lib/theme.ts`. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
      </head>
      <body>{children}</body>
    </html>
  );
}

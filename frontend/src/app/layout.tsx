import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";

import "./globals.css";

/**
 * The two faces named in `design/Sistem desain.png`.
 *
 * `next/font/google` fetches and subsets these **at build time** and serves
 * them from our own origin, so no request leaves the page for fonts.gstatic.com
 * at runtime — which is what the owner's HTML mockup did, and what NFR-PRIV
 * would rather we did not ship.
 *
 * `display: "swap"` is the honest default: the fallback stack in `globals.css`
 * paints immediately and Inter replaces it when it lands. The alternative
 * blocks text on a font file, and text is the thing people came for.
 *
 * The cost this pays: the build now needs the network the first time, and
 * D-038 records that rather than letting it be discovered on a plane.
 */
const sans = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "DataCanvas",
  description: "Deterministic AI-assisted data analysis",
  icons: { icon: "/icon.png" },
};

/**
 * Declared, not computed.
 *
 * This used to be written from JavaScript because the ground could change under
 * a user's toggle and no media query can see an attribute. D-038 removed the
 * toggle, so there is exactly one ground and it can be stated in the document
 * — which also means the browser knows it before any script runs.
 *
 * The value is `--bg` from `globals.css`. It is the one place in the codebase
 * where a palette colour is repeated, and it is repeated because a `<meta>`
 * cannot read a custom property.
 */
export const viewport: Viewport = {
  themeColor: "#000000",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
}

import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "Re:Me — The right memory. The right moment.", description: "The things you cared about, remembered at the right moment." };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}

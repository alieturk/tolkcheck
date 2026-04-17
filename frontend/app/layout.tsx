import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Tolkcheck",
  description: "AI-powered quality evaluation for IND interpreter sessions",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="nl">
      <body>{children}</body>
    </html>
  );
}

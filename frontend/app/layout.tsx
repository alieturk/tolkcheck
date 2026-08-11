import type { Metadata } from "next";
import "./globals.css";
import UserBar from "./UserBar";

export const metadata: Metadata = {
  title: "Tolkcheck",
  description: "AI-powered quality evaluation for IND interpreter sessions",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="nl">
      <body suppressHydrationWarning>
        <UserBar />
        {children}
      </body>
    </html>
  );
}

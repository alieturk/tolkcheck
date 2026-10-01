import type { Metadata } from "next";
import "./globals.css";
import UserBar from "./UserBar";

export const metadata: Metadata = {
  title: "Tolkcheck",
  description: "Signals possible deviations between what was said and how it was interpreted in IND hearings",
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

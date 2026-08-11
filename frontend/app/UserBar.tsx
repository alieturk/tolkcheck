"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getMe, logout } from "../lib/api";
import type { Me } from "../lib/types";

export default function UserBar() {
  const pathname = usePathname();
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    if (pathname === "/login") return;
    getMe().then(setMe).catch(() => {});
  }, [pathname]);

  if (pathname === "/login" || !me) return null;

  async function handleLogout() {
    await logout();
    router.push("/login");
  }

  return (
    <div className="flex items-center justify-end gap-3 bg-gray-900 text-gray-300 text-xs px-6 py-1.5">
      <span>{me.email}</span>
      <button onClick={handleLogout} className="hover:text-white transition-colors">
        Uitloggen
      </button>
    </div>
  );
}

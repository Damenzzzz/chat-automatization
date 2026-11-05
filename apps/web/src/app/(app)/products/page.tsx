import type { Metadata } from "next";

import { ProductsView } from "./view";

export const metadata: Metadata = { title: "Товары" };

export default function Page() {
  return <ProductsView />;
}

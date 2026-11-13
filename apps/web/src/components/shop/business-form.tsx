"use client";

import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { SelectField, TextField } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import { FormError } from "@/components/ui/page";
import { api, type Schemas } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useNiches } from "@/lib/niches";

export function BusinessForm({
  shop,
  saveLabel,
  onDone,
  showSaved,
}: {
  shop: Schemas["ShopOut"];
  saveLabel: string;
  onDone: (shop: Schemas["ShopOut"]) => void;
  showSaved?: boolean;
}) {
  const { titles } = useNiches();
  const [name, setName] = useState(shop.name);
  const [niche, setNiche] = useState(shop.niche ?? "");
  const [city, setCity] = useState(shop.city ?? "");
  const [links, setLinks] = useState({
    instagram: shop.links.instagram ?? "",
    website: shop.links.website ?? "",
    two_gis: shop.links.two_gis ?? "",
    kaspi: shop.links.kaspi ?? "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const result = await unwrap(
        api.PATCH("/shop", {
          body: {
            name: name.trim(),
            niche: niche || null,
            city: city.trim() || null,
            links: {
              instagram: links.instagram.trim() || null,
              website: links.website.trim() || null,
              two_gis: links.two_gis.trim() || null,
              kaspi: links.kaspi.trim() || null,
            },
          },
        }),
      );
      setSaved(true);
      onDone(result);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  const link = (key: keyof typeof links) => (event: { target: { value: string } }) =>
    setLinks({ ...links, [key]: event.target.value });

  return (
    <form onSubmit={submit} className="flex max-w-2xl flex-col gap-5">
      <div className="grid gap-5 sm:grid-cols-2">
        <TextField
          className="sm:col-span-2"
          label="Название магазина"
          hint="Так бот будет представляться покупателям."
          required
          minLength={2}
          maxLength={200}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <SelectField
          label="Что продаёте"
          value={niche}
          onChange={(event) => setNiche(event.target.value)}
        >
          <option value="">Выберите</option>
          {[...new Set([...titles, ...(shop.niche ? [shop.niche] : [])])].map((item) => (
            <option key={item}>{item}</option>
          ))}
        </SelectField>
        <TextField
          label="Город"
          maxLength={100}
          value={city}
          onChange={(event) => setCity(event.target.value)}
        />
      </div>
      <fieldset className="grid gap-5 sm:grid-cols-2">
        <legend className="mb-3 font-medium">Где вас найти, если есть</legend>
        <TextField
          label="Instagram"
          placeholder="@pion.almaty"
          value={links.instagram}
          onChange={link("instagram")}
        />
        <TextField
          label="Сайт"
          placeholder="pion.kz"
          value={links.website}
          onChange={link("website")}
        />
        <TextField
          label="2GIS"
          placeholder="Ссылка на карточку"
          value={links.two_gis}
          onChange={link("two_gis")}
        />
        <TextField
          label="Kaspi"
          placeholder="Ссылка на магазин"
          value={links.kaspi}
          onChange={link("kaspi")}
        />
      </fieldset>
      <FormError error={error} />
      {showSaved && saved && <Notice kind="success">Сохранено.</Notice>}
      <div>
        <Button type="submit" loading={busy}>
          {saveLabel}
        </Button>
      </div>
    </form>
  );
}

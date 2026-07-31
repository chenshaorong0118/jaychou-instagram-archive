import Fuse from "fuse.js";
import OpenCC from "opencc-js/t2cn";
import "./style.css";

type ItemType = "post" | "story";

interface IndexItem {
  pk: string;
  item_type: ItemType;
  published_at_utc: string;
  published_at_taipei: string;
  repository: string;
  media_commit: string;
  thumbnail_commit: string;
  path: string;
  media_count: number;
  has_image: boolean;
  has_video: boolean;
  has_audio: boolean;
  thumbnail_path: string;
  metadata_shard: string;
}

interface SearchItem {
  pk: string;
  published_at_taipei: string;
  year_month: string;
  item_type: ItemType;
  caption: string | null;
  media_count: number;
  has_image: boolean;
  has_video: boolean;
  has_audio: boolean;
  search_text_simplified: string;
}

interface MediaAsset {
  type: "image" | "video" | "audio" | "poster" | "thumbnail";
  filename: string;
  mime_type: string;
}

interface MediaPosition {
  index: number;
  kind: "image" | "video" | "image_with_audio";
  assets: MediaAsset[];
}

interface MetadataItem {
  pk: string;
  item_type: ItemType;
  published_at_taipei: string;
  caption: string | null;
  text: string | null;
  repository: string;
  media_commit: string;
  path: string;
  media: MediaPosition[];
}

interface MetadataShard {
  schema_version: number;
  year_month: string;
  items: Record<string, MetadataItem>;
}

const base = import.meta.env.BASE_URL;
const rawUrl = (repository: string, commit: string, path: string): string =>
  `https://raw.githubusercontent.com/${repository}/${commit}/${path}`;
const normalize = (value: string): string =>
  value.normalize("NFKC").toLocaleLowerCase().replace(/\s+/g, " ").trim();
const traditionalToSimplified = OpenCC.Converter({ from: "t", to: "cn" });

const gallery = requiredElement<HTMLDivElement>("gallery");
const status = requiredElement<HTMLParagraphElement>("status");
const resultCount = requiredElement<HTMLElement>("result-count");
const searchInput = requiredElement<HTMLInputElement>("search-input");
const monthFilter = requiredElement<HTMLSelectElement>("month-filter");
const typeFilter = requiredElement<HTMLSelectElement>("type-filter");
const mediaFilter = requiredElement<HTMLSelectElement>("media-filter");
const dialog = requiredElement<HTMLDialogElement>("lightbox");
const stage = requiredElement<HTMLDivElement>("lightbox-stage");
const lightboxKicker = requiredElement<HTMLParagraphElement>("lightbox-kicker");
const lightboxTitle = requiredElement<HTMLHeadingElement>("lightbox-title");
const lightboxCaption = requiredElement<HTMLParagraphElement>("lightbox-caption");
const lightboxPosition = requiredElement<HTMLParagraphElement>("lightbox-position");
const copyLink = requiredElement<HTMLButtonElement>("copy-link");
const previousButton = document.querySelector<HTMLButtonElement>(
  ".lightbox__nav--previous",
);
const nextButton = document.querySelector<HTMLButtonElement>(
  ".lightbox__nav--next",
);

let items: IndexItem[] = [];
let searchItems: SearchItem[] = [];
let currentMetadata: MetadataItem | null = null;
let currentMediaIndex = 0;
const metadataCache = new Map<string, Promise<MetadataShard>>();
let lazyObserver: IntersectionObserver | null = null;

function requiredElement<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) throw new Error(`Missing element: ${id}`);
  return element as T;
}

async function fetchText(path: string): Promise<string> {
  const response = await fetch(`${base}${path}`);
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.text();
}

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${base}${path}`);
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json() as Promise<T>;
}

async function loadData(): Promise<void> {
  const [itemsText, searchPayload] = await Promise.all([
    fetchText("index/items.jsonl"),
    fetchJson<{ schema_version: number; items: SearchItem[] }>(
      "index/search-items.json",
    ),
  ]);
  items = itemsText
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line) as IndexItem)
    .sort((a, b) =>
      `${b.published_at_taipei}:${b.pk}`.localeCompare(
        `${a.published_at_taipei}:${a.pk}`,
      ),
    );
  searchItems = searchPayload.items;
  populateMonths();
  render();
  const selected = new URL(window.location.href).searchParams.get("item");
  if (selected) {
    const item = items.find((candidate) => candidate.pk === selected);
    if (item) await openItem(item, false);
  }
}

function populateMonths(): void {
  const months = [...new Set(items.map((item) => item.published_at_taipei.slice(0, 7)))];
  for (const month of months.sort().reverse()) {
    const option = document.createElement("option");
    option.value = month;
    option.textContent = month;
    monthFilter.append(option);
  }
}

function matchedPks(): Set<string> | null {
  const query = normalize(searchInput.value);
  if (!query) return null;
  const simplifiedQuery = traditionalToSimplified(query);
  const fuse = new Fuse(searchItems, {
    keys: [
      { name: "caption", weight: 0.55 },
      { name: "search_text_simplified", weight: 0.45 },
      { name: "pk", weight: 0.2 },
    ],
    threshold: 0.32,
    ignoreLocation: true,
    useTokenSearch: true,
  });
  return new Set(
    fuse.search(simplifiedQuery).map((result) => result.item.pk),
  );
}

function filteredItems(): IndexItem[] {
  const matches = matchedPks();
  return items.filter((item) => {
    if (matches && !matches.has(item.pk)) return false;
    if (
      monthFilter.value &&
      !item.published_at_taipei.startsWith(monthFilter.value)
    ) {
      return false;
    }
    if (typeFilter.value && item.item_type !== typeFilter.value) return false;
    if (mediaFilter.value === "image" && !item.has_image) return false;
    if (mediaFilter.value === "video" && !item.has_video) return false;
    if (mediaFilter.value === "audio" && !item.has_audio) return false;
    return true;
  });
}

function render(): void {
  lazyObserver?.disconnect();
  gallery.replaceChildren();
  const visible = filteredItems();
  resultCount.textContent = String(visible.length);
  status.textContent = visible.length ? "" : "沒有符合條件的項目。";
  const groups = new Map<string, IndexItem[]>();
  for (const item of visible) {
    const month = item.published_at_taipei.slice(0, 7);
    groups.set(month, [...(groups.get(month) ?? []), item]);
  }
  for (const [month, group] of groups) {
    const section = document.createElement("section");
    section.className = "month";
    const heading = document.createElement("div");
    heading.className = "month__heading";
    heading.innerHTML = `<h2>${month}</h2><span>${group.length} items</span>`;
    const cards = document.createElement("div");
    cards.className = "month__cards";
    for (const item of group) cards.append(createCard(item));
    section.append(heading, cards);
    gallery.append(section);
  }
  installLazyLoading();
}

function createCard(item: IndexItem): HTMLButtonElement {
  const card = document.createElement("button");
  card.type = "button";
  card.className = "card";
  card.dataset.pk = item.pk;
  card.setAttribute(
    "aria-label",
    `${item.item_type} ${item.published_at_taipei}`,
  );
  const image = document.createElement("img");
  image.alt = "";
  image.loading = "lazy";
  image.decoding = "async";
  image.dataset.src = rawUrl(
    item.repository,
    item.thumbnail_commit,
    item.thumbnail_path,
  );
  const overlay = document.createElement("span");
  overlay.className = "card__overlay";
  const date = document.createElement("span");
  date.textContent = item.published_at_taipei.slice(5, 16).replace("T", " · ");
  const badges = document.createElement("span");
  badges.className = "card__badges";
  badges.textContent = [
    item.item_type.toUpperCase(),
    item.media_count > 1 ? `${item.media_count}枚` : "",
    item.has_video ? "VIDEO" : "",
    item.has_audio ? "AUDIO" : "",
  ]
    .filter(Boolean)
    .join(" · ");
  overlay.append(date, badges);
  card.append(image, overlay);
  card.addEventListener("click", () => void openItem(item));
  return card;
}

function installLazyLoading(): void {
  lazyObserver = new IntersectionObserver(
    (entries, observer) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const image = entry.target as HTMLImageElement;
        const source = image.dataset.src;
        if (source) image.src = source;
        image.removeAttribute("data-src");
        observer.unobserve(image);
      }
    },
    { rootMargin: "480px 0px" },
  );
  for (const image of gallery.querySelectorAll<HTMLImageElement>("img[data-src]")) {
    lazyObserver.observe(image);
  }
}

function loadMetadataShard(path: string): Promise<MetadataShard> {
  const existing = metadataCache.get(path);
  if (existing) return existing;
  const pending = fetchJson<MetadataShard>(path);
  metadataCache.set(path, pending);
  return pending;
}

async function openItem(item: IndexItem, updateHistory = true): Promise<void> {
  const shard = await loadMetadataShard(item.metadata_shard);
  const metadata = shard.items[item.pk];
  if (!metadata) throw new Error(`Metadata not found: ${item.pk}`);
  currentMetadata = metadata;
  currentMediaIndex = 0;
  lightboxKicker.textContent =
    `${metadata.item_type.toUpperCase()} · ${metadata.published_at_taipei}`;
  lightboxTitle.textContent = `PK ${metadata.pk}`;
  lightboxCaption.textContent =
    metadata.caption || metadata.text || "沒有文字內容";
  renderMedia();
  if (!dialog.open) dialog.showModal();
  if (updateHistory) updateItemUrl(item.pk);
}

function assetUrl(metadata: MetadataItem, asset: MediaAsset): string {
  return rawUrl(
    metadata.repository,
    metadata.media_commit,
    `${metadata.path}/${asset.filename}`,
  );
}

function renderMedia(): void {
  stage.replaceChildren();
  if (!currentMetadata) return;
  const position = currentMetadata.media[currentMediaIndex];
  if (!position) return;
  const imageAsset = position.assets.find((asset) => asset.type === "image");
  const videoAsset = position.assets.find((asset) => asset.type === "video");
  const posterAsset = position.assets.find(
    (asset) => asset.type === "poster",
  );
  if (imageAsset) {
    const image = document.createElement("img");
    image.src = assetUrl(currentMetadata, imageAsset);
    image.alt =
      currentMetadata.caption ||
      currentMetadata.text ||
      `Media ${position.index}`;
    stage.append(image);
  }
  if (videoAsset) {
    const video = document.createElement("video");
    video.controls = true;
    video.preload = "metadata";
    video.src = assetUrl(currentMetadata, videoAsset);
    if (posterAsset) video.poster = assetUrl(currentMetadata, posterAsset);
    stage.append(video);
  }
  lightboxPosition.textContent =
    `${position.index} / ${currentMetadata.media.length}`;
  const multiple = currentMetadata.media.length > 1;
  if (previousButton) previousButton.hidden = !multiple;
  if (nextButton) nextButton.hidden = !multiple;
}

function updateItemUrl(pk: string | null): void {
  const url = new URL(window.location.href);
  if (pk) url.searchParams.set("item", pk);
  else url.searchParams.delete("item");
  window.history.replaceState({}, "", url);
}

document
  .querySelector<HTMLButtonElement>(".lightbox__close")
  ?.addEventListener("click", () => dialog.close());
dialog.addEventListener("click", (event) => {
  if (event.target === dialog) dialog.close();
});
dialog.addEventListener("close", () => {
  stage.replaceChildren();
  currentMetadata = null;
  updateItemUrl(null);
});
previousButton?.addEventListener("click", () => {
  if (!currentMetadata) return;
  currentMediaIndex =
    (currentMediaIndex - 1 + currentMetadata.media.length) %
    currentMetadata.media.length;
  renderMedia();
});
nextButton?.addEventListener("click", () => {
  if (!currentMetadata) return;
  currentMediaIndex = (currentMediaIndex + 1) % currentMetadata.media.length;
  renderMedia();
});
copyLink.addEventListener("click", async () => {
  await navigator.clipboard.writeText(window.location.href);
  copyLink.textContent = "已複製";
  window.setTimeout(() => {
    copyLink.textContent = "複製連結";
  }, 1200);
});

for (const control of [searchInput, monthFilter, typeFilter, mediaFilter]) {
  control.addEventListener(control === searchInput ? "input" : "change", render);
}

document.querySelectorAll<HTMLButtonElement>("[data-view]").forEach((button) => {
  button.addEventListener("click", () => {
    const view = button.dataset.view ?? "masonry";
    gallery.className = `gallery gallery--${view}`;
    document
      .querySelectorAll<HTMLButtonElement>("[data-view]")
      .forEach((candidate) =>
        candidate.setAttribute(
          "aria-pressed",
          String(candidate === button),
        ),
      );
  });
});

void loadData().catch((error: unknown) => {
  console.error(error);
  status.textContent = "索引載入失敗，請稍後重試。";
});

const fetchBtn = document.getElementById("fetchBtn");
const videoUrlInput = document.getElementById("videoUrl");
const displayNameInput = document.getElementById("displayName");
const statusEl = document.getElementById("status");
const videoInfoEl = document.getElementById("videoInfo");
const thumbEl = document.getElementById("thumb");
const videoTitleEl = document.getElementById("videoTitle");
const platformBadgeEl = document.getElementById("platformBadge");
const qualityListEl = document.getElementById("qualityList");
const downloadResultEl = document.getElementById("downloadResult");

let currentUrl = "";

function formatSize(bytes) {
  if (!bytes) return "";
  const mb = bytes / (1024 * 1024);
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${(bytes / 1024).toFixed(0)} KB`;
}

fetchBtn.addEventListener("click", async () => {
  const url = videoUrlInput.value.trim();
  if (!url) {
    statusEl.textContent = "الرجاء لصق رابط أولاً.";
    return;
  }

  currentUrl = url;
  statusEl.textContent = "جاري جلب معلومات الفيديو...";
  qualityListEl.innerHTML = "";
  videoInfoEl.classList.add("hidden");
  downloadResultEl.classList.add("hidden");

  try {
    const res = await fetch("/api/formats", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await res.json();

    if (!data.ok) {
      statusEl.textContent = data.error || "حدث خطأ غير متوقع.";
      return;
    }

    statusEl.textContent = "";
    videoTitleEl.textContent = data.title || "بدون عنوان";
    platformBadgeEl.textContent = data.platform;
    thumbEl.src = data.thumbnail || "";
    videoInfoEl.classList.remove("hidden");

    data.formats.forEach((f) => {
      const btn = document.createElement("button");
      btn.className = "quality-btn";
      btn.textContent = `${f.label}${f.filesize ? " · " + formatSize(f.filesize) : ""}`;
      btn.addEventListener("click", () => selectQuality(btn, f.format_id));
      qualityListEl.appendChild(btn);
    });
  } catch (err) {
    statusEl.textContent = "تعذر الاتصال بالخادم.";
  }
});

async function selectQuality(btn, formatId) {
  document.querySelectorAll(".quality-btn").forEach((b) => b.classList.remove("selected"));
  btn.classList.add("selected");

  statusEl.textContent = "جاري التنزيل، قد يستغرق ذلك بعض الوقت...";
  downloadResultEl.classList.add("hidden");

  try {
    const res = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: currentUrl,
        format_id: formatId,
        display_name: displayNameInput.value.trim(),
      }),
    });
    const data = await res.json();

    if (!data.ok) {
      statusEl.textContent = data.error || "فشل التنزيل.";
      return;
    }

    statusEl.textContent = "";
    downloadResultEl.innerHTML = `تم التجهيز بنجاح: <a href="${data.download_url}" target="_blank">اضغط هنا لتنزيل "${data.title}"</a>`;
    downloadResultEl.classList.remove("hidden");
  } catch (err) {
    statusEl.textContent = "حدث خطأ أثناء التنزيل.";
  }
}

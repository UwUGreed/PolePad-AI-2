import { getSessionUser } from "@/lib/auth";
import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function SubmissionPage() {
  const user = await getSessionUser();
  if (!user) redirect("/login");

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <div className="rounded-3xl bg-white p-10 shadow-lg">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-4xl font-extrabold tracking-tight text-blue-950">
              Submission
            </h1>
            <p className="mt-2 text-blue-900/80">
              Upload site photo sets below.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <span className="text-sm font-semibold text-blue-900">Role</span>
            <span className="rounded-full bg-blue-50 px-4 py-2 text-sm font-bold text-blue-900 ring-1 ring-blue-200">
              {user.role}
            </span>
          </div>
        </div>

        <div className="mt-10">
          <h2 className="text-xl font-bold text-blue-950">Photo Uploads</h2>
          <p className="mt-1 text-sm text-blue-900/80">
            Front-end fields only (no storage yet).
          </p>

          <div className="mt-8 grid gap-8 md:grid-cols-2">
            <UploadCard
              title="Tag Photo Close-Up"
              help="Select a single image."
              multiple={false}
            />
            <UploadCard
              title="Overview Photos"
              help="You can select multiple images."
              multiple
            />
            <UploadCard
              title="Base Photos"
              help="You can select multiple images."
              multiple
            />
            <UploadCard
              title="Pad Mounted Photos"
              help="You can select multiple images."
              multiple
            />
          </div>

          <div className="mt-10 rounded-2xl bg-blue-50 px-6 py-4 text-blue-900 ring-1 ring-blue-200">
            <span className="font-bold">Note:</span> Not stored yet. (UI only)
          </div>
        </div>
      </div>
    </main>
  );
}

function UploadCard({
  title,
  help,
  multiple,
}: {
  title: string;
  help: string;
  multiple?: boolean;
}) {
  return (
    <section className="rounded-3xl bg-white p-8 shadow-sm ring-1 ring-blue-100">
      <h3 className="text-2xl font-extrabold text-blue-950">{title}</h3>

      <div className="mt-6 rounded-2xl bg-blue-50 p-6 ring-1 ring-blue-100">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <label className="text-sm font-semibold text-blue-950">
            {multiple ? "Select images" : "Select an image"}
          </label>

          <label className="inline-flex cursor-pointer items-center justify-center rounded-xl bg-white px-5 py-2 text-sm font-bold text-blue-950 shadow-sm ring-1 ring-blue-200 transition hover:shadow-md hover:ring-blue-300 active:scale-[0.98]">
            Browse
            <input
              type="file"
              className="hidden"
              multiple={!!multiple}
              accept="image/png,image/jpeg,image/webp"
            />
          </label>
        </div>

        <p className="mt-4 text-sm text-blue-900/80">{help}</p>
        <p className="mt-2 text-xs text-blue-900/60">
          Accepted: JPG, PNG, WebP
        </p>
      </div>
    </section>
  );
}
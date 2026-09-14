"""Tk vendor License Manager (RFC-0087).

Private signing key and SQLite live in %LOCALAPPDATA%\\Jarvis\\license-issuer\\.
This UI is not part of the customer installer payload.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app.licensing.vendor_issuer import (
    init_db,
    issue_customer_license,
    issuer_data_dir,
    list_licensees,
    list_licenses,
    list_modules,
    renew_customer_license,
    vendor_public_hex,
)


class LicenseManagerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Jarvis License Manager")
        self.root.minsize(720, 560)
        init_db()
        self.modules = list_modules()
        self.module_vars: dict[str, tk.BooleanVar] = {}
        self._build()
        self.refresh()

    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}
        form = ttk.LabelFrame(self.root, text="Licensee")
        form.pack(fill="x", padx=10, pady=8)

        ttk.Label(form, text="Name *").grid(row=0, column=0, sticky="w", **pad)
        self.name = tk.StringVar()
        ttk.Entry(form, textvariable=self.name, width=40).grid(row=0, column=1, sticky="ew", **pad)

        ttk.Label(form, text="Email *").grid(row=1, column=0, sticky="w", **pad)
        self.email = tk.StringVar()
        ttk.Entry(form, textvariable=self.email, width=40).grid(row=1, column=1, sticky="ew", **pad)

        ttk.Label(form, text="Address").grid(row=2, column=0, sticky="w", **pad)
        self.address = tk.StringVar()
        ttk.Entry(form, textvariable=self.address, width=40).grid(row=2, column=1, sticky="ew", **pad)

        self.le = tk.BooleanVar(value=False)
        ttk.Checkbutton(form, text="Law enforcement (required for Red)", variable=self.le).grid(
            row=3, column=1, sticky="w", **pad
        )

        mods = ttk.LabelFrame(self.root, text="Modules")
        mods.pack(fill="x", padx=10, pady=4)
        for index, item in enumerate(self.modules):
            var = tk.BooleanVar(value=item["id"] == "blue-team")
            self.module_vars[item["id"]] = var
            label = item["label"] + (" (LE)" if item["requires_le"] else "")
            ttk.Checkbutton(mods, text=label, variable=var).grid(
                row=index // 2, column=index % 2, sticky="w", padx=8, pady=2
            )

        term = ttk.LabelFrame(self.root, text="Term")
        term.pack(fill="x", padx=10, pady=4)
        ttk.Label(term, text="Term days").grid(row=0, column=0, sticky="w", **pad)
        self.term_days = tk.StringVar(value="90")
        ttk.Entry(term, textvariable=self.term_days, width=8).grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(term, text="Max days (autorenew cap)").grid(row=0, column=2, sticky="w", **pad)
        self.max_days = tk.StringVar(value="365")
        ttk.Entry(term, textvariable=self.max_days, width=8).grid(row=0, column=3, sticky="w", **pad)
        self.auto_renew = tk.BooleanVar(value=False)
        ttk.Checkbutton(term, text="Auto-renew locally up to max", variable=self.auto_renew).grid(
            row=1, column=1, columnspan=3, sticky="w", **pad
        )

        buttons = ttk.Frame(self.root)
        buttons.pack(fill="x", padx=10, pady=6)
        ttk.Button(buttons, text="Generate sealed license", command=self.generate).pack(side="left", padx=4)
        ttk.Button(buttons, text="Renew selected", command=self.renew).pack(side="left", padx=4)
        ttk.Button(buttons, text="Refresh", command=self.refresh).pack(side="left", padx=4)

        info = ttk.LabelFrame(self.root, text="Vendor key (public only — private stays on this PC)")
        info.pack(fill="x", padx=10, pady=4)
        self.pubkey = tk.StringVar(value=vendor_public_hex())
        ttk.Entry(info, textvariable=self.pubkey, state="readonly").pack(fill="x", padx=8, pady=6)
        ttk.Label(
            info,
            text=f"Database: {issuer_data_dir()}  ·  Copy the .trusted.pub file next to a license onto the Leader as data/cyber-ato/trusted.pub",
            wraplength=680,
        ).pack(anchor="w", padx=8, pady=(0, 6))

        table = ttk.LabelFrame(self.root, text="Issued licenses")
        table.pack(fill="both", expand=True, padx=10, pady=8)
        columns = ("license_id", "email", "modules", "expires_at", "max_expires_at")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", height=8)
        for column in columns:
            self.tree.heading(column, text=column)
            self.tree.column(column, width=140)
        self.tree.pack(fill="both", expand=True, padx=6, pady=6)

    def _selected_modules(self) -> list[str]:
        return [module_id for module_id, var in self.module_vars.items() if var.get()]

    def generate(self) -> None:
        try:
            output = filedialog.askdirectory(title="Save sealed license in…")
            if not output:
                return
            result = issue_customer_license(
                name=self.name.get(),
                email=self.email.get(),
                address=self.address.get(),
                law_enforcement=self.le.get(),
                modules=self._selected_modules(),
                term_days=int(self.term_days.get() or "90"),
                max_days=int(self.max_days.get() or "365"),
                auto_renew=self.auto_renew.get(),
                output_dir=Path(output),
            )
        except Exception as exc:
            messagebox.showerror("Issue failed", str(exc))
            return
        self.refresh()
        messagebox.showinfo(
            "Issued",
            f"Wrote {result['sealed_path']}\nPin: {result['trusted_pub_path']}",
        )

    def renew(self) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Renew", "Select a license row first.")
            return
        license_id = self.tree.item(selected[0], "values")[0]
        try:
            output = filedialog.askdirectory(title="Save renewed license in…")
            if not output:
                return
            result = renew_customer_license(str(license_id), output_dir=Path(output))
        except Exception as exc:
            messagebox.showerror("Renew failed", str(exc))
            return
        self.refresh()
        messagebox.showinfo("Renewed", f"Wrote {result['sealed_path']}")

    def refresh(self) -> None:
        for row in self.tree.get_children():
            self.tree.delete(row)
        licensees = {item["id"]: item for item in list_licensees()}
        for item in list_licenses():
            person = licensees.get(item.get("licensee_id") or "", {})
            modules = item.get("modules") or []
            self.tree.insert(
                "",
                "end",
                values=(
                    item.get("license_id") or "",
                    person.get("email") or "",
                    ",".join(modules),
                    item.get("expires_at") or "",
                    item.get("max_expires_at") or "",
                ),
            )


def main() -> None:
    root = tk.Tk()
    LicenseManagerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

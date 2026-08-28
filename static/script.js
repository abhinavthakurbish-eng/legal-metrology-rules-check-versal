// Upload page ka interactivity: multi-image preview grid + drag-drop + loading state
document.addEventListener("DOMContentLoaded", function () {
    const dropzone = document.getElementById("dropzone");
    const fileInput = document.getElementById("label_images");
    const previewGrid = document.getElementById("preview-grid");
    const emptyState = document.getElementById("dropzone-empty");
    const form = document.getElementById("scan-form");
    const submitBtn = document.getElementById("submit-btn");
    const btnText = document.getElementById("btn-text");

    if (!dropzone) return; // is page pe dropzone nahi hai toh kuch mat karo

    // Selected files ko humesha ek DataTransfer object mein rakhte hain -
    // isse multiple selections (drag-drop + file-picker, alag alag baar) sab
    // milaake accumulate hote hain, aur remove button se ek-ek hataana bhi
    // aasaan ho jaata hai.
    let selectedFiles = new DataTransfer();

    dropzone.addEventListener("click", (e) => {
        if (e.target.closest(".preview-remove")) return; // remove button pe click ho toh file-picker mat kholo
        fileInput.click();
    });

    fileInput.addEventListener("change", () => {
        addFiles(fileInput.files);
    });

    ["dragover", "dragenter"].forEach(evt => {
        dropzone.addEventListener(evt, (e) => {
            e.preventDefault();
            dropzone.classList.add("dragover");
        });
    });

    ["dragleave", "drop"].forEach(evt => {
        dropzone.addEventListener(evt, (e) => {
            e.preventDefault();
            dropzone.classList.remove("dragover");
        });
    });

    dropzone.addEventListener("drop", (e) => {
        if (e.dataTransfer.files && e.dataTransfer.files.length) {
            addFiles(e.dataTransfer.files);
        }
    });

    function addFiles(fileList) {
        for (const file of fileList) {
            if (file.type.startsWith("image/")) {
                selectedFiles.items.add(file);
            }
        }
        fileInput.files = selectedFiles.files;
        renderPreviews();
    }

    function removeFile(index) {
        const updated = new DataTransfer();
        Array.from(selectedFiles.files).forEach((file, i) => {
            if (i !== index) updated.items.add(file);
        });
        selectedFiles = updated;
        fileInput.files = selectedFiles.files;
        renderPreviews();
    }

    function renderPreviews() {
        previewGrid.innerHTML = "";
        const files = Array.from(selectedFiles.files);

        if (files.length === 0) {
            previewGrid.style.display = "none";
            emptyState.style.display = "block";
            return;
        }

        emptyState.style.display = "none";
        previewGrid.style.display = "grid";

        files.forEach((file, index) => {
            const reader = new FileReader();
            const thumb = document.createElement("div");
            thumb.className = "preview-thumb";

            const img = document.createElement("img");
            const label = document.createElement("span");
            label.className = "preview-side-label";
            label.textContent = "Side " + (index + 1);

            const removeBtn = document.createElement("button");
            removeBtn.type = "button";
            removeBtn.className = "preview-remove";
            removeBtn.textContent = "✕";
            removeBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                removeFile(index);
            });

            reader.onload = (e) => { img.src = e.target.result; };
            reader.readAsDataURL(file);

            thumb.appendChild(img);
            thumb.appendChild(label);
            thumb.appendChild(removeBtn);
            previewGrid.appendChild(thumb);
        });

        // "aur photos add karo" tile
        const addMore = document.createElement("div");
        addMore.className = "preview-add-more";
        addMore.innerHTML = "<span>+</span><p>Add another side</p>";
        addMore.addEventListener("click", (e) => {
            e.stopPropagation();
            fileInput.click();
        });
        previewGrid.appendChild(addMore);
    }

    form.addEventListener("submit", (e) => {
        if (!selectedFiles.files || selectedFiles.files.length === 0) {
            e.preventDefault();
            alert("Kam se kam ek product photo upload karo (front side se shuru kar sakte ho).");
            return;
        }
        submitBtn.disabled = true;
        btnText.textContent = "Scanning label... please wait";
    });
});

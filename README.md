# Appalachian A.I. Corps Website

## Setup Instructions

### 1. Add Your Logo/Graphic
Create an `assets` folder in the root directory and add your graphic as `logo.png`:

```bash
mkdir assets
# Copy your graphic to assets/logo.png
```

### 2. Install Quarto (if not already installed)
Download and install Quarto from: https://quarto.org/docs/get-started/

### 3. Preview the Site Locally
```bash
quarto preview
```

### 4. Build the Site
```bash
quarto render
```

This will generate the site in the `_site` directory.

### 5. Deploy to GitHub Pages

You have two options:

#### Option A: Render locally and push _site contents
```bash
quarto render
git add _site
git commit -m "Build site"
git push
```

Then configure GitHub Pages to use the `_site` directory.

#### Option B: Use GitHub Actions (Recommended)
GitHub Pages can automatically render Quarto sites. Just push your `.qmd` files and configure GitHub Pages to use GitHub Actions as the source.

1. Push the source files:
```bash
git add .
git commit -m "Add Quarto homepage"
git push
```

2. In your repo settings under Pages, select "GitHub Actions" as the source.

## File Structure

```
web/
├── index.qmd          # Main homepage
├── styles.css         # Custom styling with Appalachian colors
├── _quarto.yml        # Quarto configuration
├── assets/
│   └── logo.png       # Your logo/graphic
└── modules/
    └── water-quality/ # Your water quality module
```

## Customization

### Colors
All colors are defined in `styles.css` using CSS variables. The Tennessee Orange (#FF8200) is used as the primary action color, with Valley (#00746F) and Globe (#006C93) creating the gradient background.

### Content
Edit `index.qmd` to update the text, add more modules, or modify the layout.

### Navigation
Update the navbar in `_quarto.yml` to add or modify menu items.

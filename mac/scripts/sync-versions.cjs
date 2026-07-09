const fs = require('fs');
const path = require('path');

// 1. Read the single source of truth version from package.json
const packageJsonPath = path.join(__dirname, '../package.json');
const pkg = JSON.parse(fs.readFileSync(packageJsonPath, 'utf8'));
const version = pkg.version;

if (!version) {
  console.error('Error: Could not find version in package.json');
  process.exit(1);
}

console.log(`Syncing version v${version} to other configuration files...`);

// 2. Synchronize TokenTrackerBar/project.yml
const projectYmlPath = path.join(__dirname, '../TokenTrackerBar/project.yml');
if (fs.existsSync(projectYmlPath)) {
  const projectYml = fs.readFileSync(projectYmlPath, 'utf8');
  const updatedYml = projectYml.replace(
    /(MARKETING_VERSION:\s*")([^"]+)(")/g,
    `$1${version}$3`
  );
  fs.writeFileSync(projectYmlPath, updatedYml, 'utf8');
  console.log(`✓ Synchronized version in TokenTrackerBar/project.yml`);
} else {
  console.warn(`⚠️ Warning: project.yml not found at ${projectYmlPath}`);
}

// 3. Synchronize TokenTrackerWin/TokenTrackerWin.csproj
const csprojPath = path.join(__dirname, '../TokenTrackerWin/TokenTrackerWin.csproj');
if (fs.existsSync(csprojPath)) {
  const csproj = fs.readFileSync(csprojPath, 'utf8');
  const updatedCsproj = csproj.replace(
    /(<Version>)([^<]+)(<\/Version>)/g,
    `$1${version}$3`
  );
  fs.writeFileSync(csprojPath, updatedCsproj, 'utf8');
  console.log(`✓ Synchronized version in TokenTrackerWin/TokenTrackerWin.csproj`);
} else {
  console.warn(`⚠️ Warning: TokenTrackerWin.csproj not found at ${csprojPath}`);
}

console.log('✓ Version synchronization completed successfully.');

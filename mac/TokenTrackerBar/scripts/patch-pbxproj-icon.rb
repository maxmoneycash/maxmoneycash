#!/usr/bin/env ruby
# frozen_string_literal: true

# patch-pbxproj-icon.rb
# Injects AppIcon.icon (Icon Composer format) into the Xcode project
# as a proper folder.iconcomposer.icon file reference in the Resources build phase.
#
# Run after `xcodegen generate`:
#   ruby scripts/patch-pbxproj-icon.rb

require 'securerandom'

PBXPROJ = File.join(__dir__, '..', 'TokenTrackerBar.xcodeproj', 'project.pbxproj')

def gen_id
  SecureRandom.hex(12).upcase
end

content = File.read(PBXPROJ)

# Skip if already patched
if content.include?('folder.iconcomposer.icon')
  puts "Already patched — AppIcon.icon reference exists."
  exit 0
end

file_ref_id = gen_id
build_file_id = gen_id

# 1. Add PBXFileReference for AppIcon.icon (before End PBXFileReference)
file_ref_line = "\t\t#{file_ref_id} /* AppIcon.icon */ = {isa = PBXFileReference; lastKnownFileType = folder.iconcomposer.icon; path = AppIcon.icon; sourceTree = \"<group>\"; };\n"

content.sub!('/* End PBXFileReference section */') do |m|
  "#{file_ref_line}#{m}"
end

# 2. Add PBXBuildFile for AppIcon.icon in Resources (before End PBXBuildFile)
build_file_line = "\t\t#{build_file_id} /* AppIcon.icon in Resources */ = {isa = PBXBuildFile; fileRef = #{file_ref_id} /* AppIcon.icon */; };\n"

content.sub!('/* End PBXBuildFile section */') do |m|
  "#{build_file_line}#{m}"
end

# 3. Add to the inner TokenTrackerBar group's children
# This group has `path = TokenTrackerBar;` and contains Assets.xcassets, Swift files, etc.
# We insert after Assets.xcassets in that group
content.sub!(%r{(6E651075DB834A2DD6917AAD /\* Assets\.xcassets \*/,)}) do
  "#{$1}\n\t\t\t\t#{file_ref_id} /* AppIcon.icon */,"
end

# 4. Add to PBXResourcesBuildPhase files list
# Insert into the files = ( ... ) array
# Match the Resources build phase files list and append our entry
content.sub!(/(isa = PBXResourcesBuildPhase;.*?files = \()([^)]*)\)/m) do
  prefix = $1
  existing = $2.rstrip
  "#{prefix}#{existing}\n\t\t\t\t#{build_file_id} /* AppIcon.icon in Resources */,\n\t\t\t)"
end

File.write(PBXPROJ, content)
puts "Patched: AppIcon.icon added as folder.iconcomposer.icon resource"

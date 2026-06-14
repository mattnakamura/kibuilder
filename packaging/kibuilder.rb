# Homebrew cask for kibuilder.
#
# This file lives in the *tap* repo, not here — copy it to
# github.com/mattnakamura/homebrew-tap as Casks/kibuilder.rb and fill in
# the sha256 values printed by scripts/make_dmg.sh (or the CI release log).
#
# Users then install with:
#   brew tap mattnakamura/tap
#   brew install --cask kibuilder

cask "kibuilder" do
  arch arm: "arm64", intel: "x86_64"

  version "0.1.1"
  sha256 arm:   "8ae6f4fddbc9243fcb47cf12ddeb2fca501332d15400a1f9fdb1d6f66c92209d",
         intel: "2fd675783009d758a706e1e9d83192ef9b7eda9feec5c803c49276e94947d402"

  url "https://github.com/mattnakamura/kibuilder/releases/download/v#{version}/kibuilder-#{version}-#{arch}.dmg"
  name "kibuilder"
  desc "Visual step-by-step assembly guides from KiCAD PCBs"
  homepage "https://github.com/mattnakamura/kibuilder"

  livecheck do
    url :url
    strategy :github_latest
  end

  depends_on macos: ">= :big_sur"

  app "kibuilder.app"

  caveats <<~EOS
    Board renders require KiCad's command-line tools:
      brew install --cask kicad
  EOS

  zap trash: [
    "~/Library/Preferences/io.github.mattnakamura.kibuilder.plist",
    "~/Library/Saved Application State/io.github.mattnakamura.kibuilder.savedState",
  ]
end

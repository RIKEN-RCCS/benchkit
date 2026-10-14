#!/bin/bash
# Keep interception after compiler/tool modules prepend directories to PATH.
# The wrapper resolves the real executable from the current module environment.
make() { command bash "${BK_BENCHKIT_ROOT}/scripts/build_tool_wrappers/bk_build_tool_wrapper.sh" make "$@"; }
cmake() { command bash "${BK_BENCHKIT_ROOT}/scripts/build_tool_wrappers/bk_build_tool_wrapper.sh" cmake "$@"; }
ninja() { command bash "${BK_BENCHKIT_ROOT}/scripts/build_tool_wrappers/bk_build_tool_wrapper.sh" ninja "$@"; }
export -f make cmake ninja
export BK_BUILD_TOOL_FUNCTION_WRAPPERS=true

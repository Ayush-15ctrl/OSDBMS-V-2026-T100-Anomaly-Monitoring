#pragma once

#include "storage.hpp"

#include <cstddef>
#include <cstdint>
#include <memory>

namespace bams {

class BufferPool {
public:
    // A bounded cache models a finite set of OS/database buffer frames.
    BufferPool(std::size_t capacity, StorageEngine& storage);
    ~BufferPool();

    BufferPool(const BufferPool&) = delete;
    BufferPool& operator=(const BufferPool&) = delete;

    // Returns a cached page or loads it from storage, promoting it to MRU.
    std::shared_ptr<Page> get_page(std::uint64_t page_id);

    // Prevents a page from being selected by the replacement policy.
    void pin_page(std::uint64_t page_id);

    // Removes one pin; an unpinned page becomes eligible for replacement.
    void unpin_page(std::uint64_t page_id);

    // LRU eviction - analogous to an OS page replacement policy.
    bool evict_if_needed();

    // Returns the number of resident pages for observability and tests.
    std::size_t size() const noexcept;

private:
    struct LruNode;

    // The hash map provides lookup; explicit node links provide visible LRU pointer manipulation.
    std::unique_ptr<LruNode> head_;
    LruNode* tail_{};
    std::size_t capacity_{};
    StorageEngine& storage_;
};

}  // namespace bams

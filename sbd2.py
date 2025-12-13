import sys
import random
import pickle
import math
import os
import struct
import matplotlib.pyplot as plt

# --- KONFIGURACJA SYMULACJI ---
PAGE_SIZE = 512  # Stały rozmiar strony w bajtach


class DiskStats:
    """Klasa pomocnicza do zliczania operacji dyskowych."""

    def __init__(self):
        self.reads = 0
        self.writes = 0

    def reset(self):
        self.reads = 0
        self.writes = 0

    def __str__(self):
        return f"Odczyty: {self.reads}, Zapisy: {self.writes}"


# Globalne statystyki
stats = DiskStats()


class DiskManager:
    """
    Symuluje dysk twardy na surowym pliku binarnym.
    Plik jest podzielony na bloki o stałej wielkości (PAGE_SIZE).
    """

    def __init__(self, filename):
        self.filename = filename + ".bin"
        self.page_size = PAGE_SIZE

        if not os.path.exists(self.filename):
            with open(self.filename, 'wb') as f:
                # Format: [Next_Page_ID (4B int)] [Root_ID (4B int)] [Padding...]
                f.write(struct.pack('ii', 1, -1))
                f.write(b'\x00' * (self.page_size - 8))

        self.file = open(self.filename, 'r+b')

    def _read_metadata(self):
        self.file.seek(0)
        data = self.file.read(8)
        return struct.unpack('ii', data)

    def _write_metadata(self, next_page_id, root_id):
        self.file.seek(0)
        self.file.write(struct.pack('ii', next_page_id, root_id))

    def get_root_id(self):
        _, root_id = self._read_metadata()
        return root_id if root_id != -1 else None

    def set_root_id(self, root_id):
        next_id, _ = self._read_metadata()
        self._write_metadata(next_id, root_id if root_id is not None else -1)

    def get_next_page_id(self):
        next_id, _ = self._read_metadata()
        return next_id

    def read_page(self, page_id):
        if page_id is None: return None
        stats.reads += 1

        offset = page_id * self.page_size
        self.file.seek(offset)
        raw_data = self.file.read(self.page_size)

        if not raw_data or raw_data == b'\x00' * self.page_size:
            return None

        try:
            return pickle.loads(raw_data)
        except (pickle.UnpicklingError, EOFError):
            return None

    def write_page(self, page_id, data_obj):
        stats.writes += 1
        next_id, root_id = self._read_metadata()

        if page_id is None:
            page_id = next_id
            next_id += 1
            self._write_metadata(next_id, root_id)

        serialized_data = pickle.dumps(data_obj)

        if len(serialized_data) > self.page_size:
            raise ValueError(f"CRITICAL: Obiekt za duży ({len(serialized_data)} B) dla strony ({self.page_size} B).")

        padding = b'\x00' * (self.page_size - len(serialized_data))
        final_block = serialized_data + padding

        offset = page_id * self.page_size
        self.file.seek(offset)
        self.file.write(final_block)

        return page_id

    def delete_page(self, page_id):
        offset = page_id * self.page_size
        self.file.seek(offset)
        self.file.write(b'\x00' * self.page_size)

    def get_file_size(self):
        self.file.flush()
        return os.path.getsize(self.filename)

    def close(self):
        self.file.close()

    def clear(self):
        self.file.close()
        if os.path.exists(self.filename):
            os.remove(self.filename)
        with open(self.filename, 'wb') as f:
            f.write(struct.pack('ii', 1, -1))
            f.write(b'\x00' * (self.page_size - 8))
        self.file = open(self.filename, 'r+b')


class Record:
    def __init__(self, key, numbers):
        self.key = key
        self.numbers = numbers
        self.sum = sum(numbers)
        self.is_deleted = False

    def __repr__(self):
        return f"[ID: {self.key} | Liczby: {self.numbers} | Suma: {self.sum}]"


class BTreeNode:
    def __init__(self, is_leaf=False):
        self.is_leaf = is_leaf
        self.keys = []
        self.values = []
        self.children = []

    def __repr__(self):
        return f"Node(Leaf={self.is_leaf}, Keys={self.keys})"


class DataFileManager:
    def __init__(self, disk):
        self.disk = disk
        self.free_pages = []

    def insert_record(self, record):
        page_id = None
        if self.free_pages:
            page_id = self.free_pages.pop()
        real_id = self.disk.write_page(page_id, record)
        return real_id

    def read_record(self, page_id):
        return self.disk.read_page(page_id)

    def update_record(self, page_id, new_numbers):
        record = self.read_record(page_id)
        if record:
            record.numbers = new_numbers
            record.sum = sum(new_numbers)
            self.disk.write_page(page_id, record)
            return True
        return False

    def delete_record(self, page_id):
        self.free_pages.append(page_id)
        self.disk.delete_page(page_id)


# --- IMPLEMENTACJA B-DRZEWA ---

class BTree:
    def __init__(self, d, index_disk, data_manager):
        self.d = d
        self.disk = index_disk
        self.data_mgr = data_manager
        self.root_id = self.disk.get_root_id()

        if self.root_id is None:
            root = BTreeNode(is_leaf=True)
            self.root_id = self.disk.write_page(None, root)
            self.disk.set_root_id(self.root_id)

    def get_node(self, node_id):
        return self.disk.read_page(node_id)

    def save_node(self, node_id, node):
        self.disk.write_page(node_id, node)

    def update_root(self, new_root_id):
        self.root_id = new_root_id
        self.disk.set_root_id(self.root_id)

    # --- WYSZUKIWANIE ---
    def search(self, key, node_id=None):
        if node_id is None: node_id = self.root_id
        node = self.get_node(node_id)
        if node is None: return None, None, None

        i = 0
        while i < len(node.keys) and key > node.keys[i]:
            i += 1

        if i < len(node.keys) and key == node.keys[i]:
            return self.data_mgr.read_record(node.values[i]), node_id, i

        if node.is_leaf:
            return None, None, None

        return self.search(key, node.children[i])

    # --- WSTAWIANIE ZGODNE Z WYKŁADEM (BOTTOM-UP z KOMPENSACJĄ) ---
    def insert(self, key, numbers):
        # 1. Sprawdź duplikat
        rec, _, _ = self.search(key)
        if rec:
            return False

        # 2. Zapisz dane
        new_record = Record(key, numbers)
        try:
            data_addr = self.data_mgr.insert_record(new_record)
        except ValueError as e:
            print(f"Błąd zapisu rekordu: {e}")
            return False

        # 3. Znajdź liść i ścieżkę do niego
        path = self._get_path_to_leaf(self.root_id, key)
        if not path:
            return False
            
        leaf_id = path[-1]
        leaf = self.get_node(leaf_id)

        # 4. Wstaw posortowane do liścia
        self._insert_to_node_local(leaf, key, data_addr, None)
        self.save_node(leaf_id, leaf)

        # 5. Obsługa przepełnienia (Overflow) w górę drzewa
        curr_id = leaf_id
        curr_node = leaf
        
        # Bezpieczne usunięcie liścia ze ścieżki
        if path:
            path.pop() 
        
        while len(curr_node.keys) > 2 * self.d:
            # Jeśli to korzeń (ścieżka pusta), musimy go podzielić
            if not path:
                new_root = BTreeNode(is_leaf=False)
                new_root.children.append(curr_id)
                self._split_child_manual(new_root, 0, curr_node, curr_id)
                new_root_id = self.disk.write_page(None, new_root)
                self.update_root(new_root_id)
                return True
            
            parent_id = path[-1]
            parent = self.get_node(parent_id)
            
            # Znajdź indeks u rodzica
            idx_in_parent = -1
            for i, child_id in enumerate(parent.children):
                if child_id == curr_id:
                    idx_in_parent = i
                    break
            
            # Kompensacja
            compensated = False
            if idx_in_parent != -1:
                # Sprawdź lewego sąsiada
                if idx_in_parent > 0:
                    left_sib_id = parent.children[idx_in_parent - 1]
                    left_sib = self.get_node(left_sib_id)
                    if len(left_sib.keys) < 2 * self.d:
                        self._compensate_left(left_sib, left_sib_id, parent, curr_node, curr_id, idx_in_parent - 1)
                        self.save_node(parent_id, parent)
                        compensated = True
                
                # Sprawdź prawego sąsiada
                if not compensated and idx_in_parent < len(parent.children) - 1:
                    right_sib_id = parent.children[idx_in_parent + 1]
                    right_sib = self.get_node(right_sib_id)
                    if len(right_sib.keys) < 2 * self.d:
                        self._compensate_right(curr_node, curr_id, parent, right_sib, right_sib_id, idx_in_parent)
                        self.save_node(parent_id, parent)
                        compensated = True
            
            if compensated:
                return True 
                
            # --- SPLIT ---
            target_idx = idx_in_parent if idx_in_parent != -1 else 0
            self._split_child_manual(parent, target_idx, curr_node, curr_id)
            self.save_node(parent_id, parent)
            
            curr_id = parent_id
            curr_node = parent
            
            # Bezpieczne przejście w górę
            if path:
                path.pop()

        return True

    def _get_path_to_leaf(self, node_id, key):
        path = []
        curr = node_id
        while True:
            path.append(curr)
            node = self.get_node(curr)
            if node is None: break 
            if node.is_leaf:
                break
            i = 0
            while i < len(node.keys) and key > node.keys[i]:
                i += 1
            if i >= len(node.children):
                curr = node.children[-1]
            else:
                curr = node.children[i]
        return path

    def _insert_to_node_local(self, node, key, val, child_right_id):
        i = len(node.keys) - 1
        node.keys.append(0)
        node.values.append(0)
        if not node.is_leaf and child_right_id is not None:
             node.children.append(None)

        while i >= 0 and key < node.keys[i]:
            node.keys[i+1] = node.keys[i]
            node.values[i+1] = node.values[i]
            if not node.is_leaf:
                node.children[i+2] = node.children[i+1]
            i -= 1
        
        node.keys[i+1] = key
        node.values[i+1] = val
        if not node.is_leaf and child_right_id is not None:
            node.children[i+2] = child_right_id

    def _split_child_manual(self, parent, index, child, child_id):
        mid_idx = self.d
        mid_key = child.keys[mid_idx]
        mid_val = child.values[mid_idx]
        
        new_node = BTreeNode(is_leaf=child.is_leaf)
        
        new_node.keys = child.keys[mid_idx+1:]
        new_node.values = child.values[mid_idx+1:]
        if not child.is_leaf:
            new_node.children = child.children[mid_idx+1:]
            
        child.keys = child.keys[:mid_idx]
        child.values = child.values[:mid_idx]
        if not child.is_leaf:
            child.children = child.children[:mid_idx+1]
            
        new_node_id = self.disk.write_page(None, new_node)
        self.save_node(child_id, child)
        
        parent.keys.insert(index, mid_key)
        parent.values.insert(index, mid_val)
        parent.children.insert(index + 1, new_node_id)

    def _compensate_right(self, left, left_id, parent, right, right_id, separator_idx):
        """Przenosi klucz z Lewego do Prawego (Source=Left, Target=Right)."""
        right.keys.insert(0, parent.keys[separator_idx])
        right.values.insert(0, parent.values[separator_idx])
        
        if not right.is_leaf and left.children:
            right.children.insert(0, left.children.pop())
            
        parent.keys[separator_idx] = left.keys.pop()
        parent.values[separator_idx] = left.values.pop()
        
        self.save_node(left_id, left)
        self.save_node(right_id, right)
        
    def _compensate_left(self, left, left_id, parent, right, right_id, separator_idx):
        """Przenosi klucz z Prawego do Lewego (Source=Right, Target=Left)."""
        left.keys.append(parent.keys[separator_idx])
        left.values.append(parent.values[separator_idx])
        
        if not left.is_leaf and right.children:
            left.children.append(right.children.pop(0))
            
        parent.keys[separator_idx] = right.keys.pop(0)
        parent.values[separator_idx] = right.values.pop(0)
        
        self.save_node(left_id, left)
        self.save_node(right_id, right)


    # --- USUWANIE ---
    def delete(self, key):
        path = self._get_path_to_node(self.root_id, key)
        if not path:
            print(f"Klucz {key} nie istnieje.")
            return False
            
        target_id, target_idx = path[-1]
        target_node = self.get_node(target_id)
        
        if not target_node.is_leaf:
            curr = target_node.children[target_idx]
            path_to_pred = [curr]
            while True:
                n = self.get_node(curr)
                if n.is_leaf: break
                curr = n.children[-1]
                path_to_pred.append(curr)
                
            pred_node_id = path_to_pred[-1]
            pred_node = self.get_node(pred_node_id)
            
            target_node.keys[target_idx] = pred_node.keys[-1]
            target_node.values[target_idx] = pred_node.values[-1]
            self.save_node(target_id, target_node)
            
            full_path_ids = [p[0] for p in path[:-1]] + [target_id] + path_to_pred
            leaf_id = pred_node_id
            leaf = pred_node
            del leaf.keys[-1]
            del leaf.values[-1]
            self.save_node(leaf_id, leaf)
        else:
            self.data_mgr.delete_record(target_node.values[target_idx])
            del target_node.keys[target_idx]
            del target_node.values[target_idx]
            self.save_node(target_id, target_node)
            full_path_ids = [p[0] for p in path]

        curr_id = full_path_ids.pop()
        curr_node = self.get_node(curr_id)
        
        while len(curr_node.keys) < self.d:
            if not full_path_ids:
                if len(curr_node.keys) == 0 and not curr_node.is_leaf:
                    new_root_id = curr_node.children[0]
                    self.disk.delete_page(curr_id)
                    self.update_root(new_root_id)
                return True
            
            parent_id = full_path_ids[-1]
            parent = self.get_node(parent_id)
            
            idx_in_parent = -1
            for i, child_id in enumerate(parent.children):
                if child_id == curr_id:
                    idx_in_parent = i
                    break
                    
            compensated = False
            
            if idx_in_parent > 0:
                left_sib_id = parent.children[idx_in_parent - 1]
                left_sib = self.get_node(left_sib_id)
                if len(left_sib.keys) > self.d:
                    self._compensate_right(left_sib, left_sib_id, parent, curr_node, curr_id, idx_in_parent - 1)
                    self.save_node(parent_id, parent)
                    compensated = True
            
            if not compensated and idx_in_parent < len(parent.children) - 1:
                right_sib_id = parent.children[idx_in_parent + 1]
                right_sib = self.get_node(right_sib_id)
                if len(right_sib.keys) > self.d:
                    self._compensate_left(curr_node, curr_id, parent, right_sib, right_sib_id, idx_in_parent)
                    self.save_node(parent_id, parent)
                    compensated = True
            
            if compensated: return True
                
            if idx_in_parent > 0:
                left_sib_id = parent.children[idx_in_parent - 1]
                left_sib = self.get_node(left_sib_id)
                self._merge_nodes(left_sib, left_sib_id, parent, curr_node, curr_id, idx_in_parent - 1)
            else:
                right_sib_id = parent.children[idx_in_parent + 1]
                right_sib = self.get_node(right_sib_id)
                self._merge_nodes(curr_node, curr_id, parent, right_sib, right_sib_id, idx_in_parent)
            
            self.save_node(parent_id, parent)
            curr_id = parent_id
            curr_node = parent
            full_path_ids.pop()
            
        return True

    def _get_path_to_node(self, node_id, key):
        curr = node_id
        path = []
        while True:
            node = self.get_node(curr)
            if not node: return []
            i = 0
            while i < len(node.keys) and key > node.keys[i]:
                i += 1
            if i < len(node.keys) and key == node.keys[i]:
                path.append((curr, i))
                return path
            if node.is_leaf:
                return []
            path.append((curr, i))
            curr = node.children[i]

    def _merge_nodes(self, left, left_id, parent, right, right_id, separator_idx):
        left.keys.append(parent.keys[separator_idx])
        left.values.append(parent.values[separator_idx])
        
        left.keys.extend(right.keys)
        left.values.extend(right.values)
        if not left.is_leaf:
            left.children.extend(right.children)
            
        del parent.keys[separator_idx]
        del parent.values[separator_idx]
        del parent.children[separator_idx + 1]
        
        self.disk.delete_page(right_id)
        self.save_node(left_id, left)

    def update(self, key, new_numbers):
        rec, node_id, idx = self.search(key)
        if rec:
            node = self.get_node(node_id)
            data_page_id = node.values[idx]
            try:
                self.data_mgr.update_record(data_page_id, new_numbers)
                print(f"Zaktualizowano klucz {key}.")
                return True
            except ValueError as e:
                print(f"Błąd aktualizacji: {e}")
                return False
        else:
            print(f"Klucz {key} nie istnieje.")
            return False

    def print_ordered_records(self):
        print("\n=== Sekwencyjny odczyt bazy (wg klucza) ===")
        if self.root_id is not None:
            self._traverse_and_print(self.root_id)
        else:
            print("Drzewo jest puste.")
        print("===========================================\n")

    def _traverse_and_print(self, node_id):
        node = self.get_node(node_id)
        if not node: return
        for i in range(len(node.keys)):
            if not node.is_leaf:
                self._traverse_and_print(node.children[i])
            key = node.keys[i]
            record_addr = node.values[i]
            record = self.data_mgr.read_record(record_addr)
            print(f"Klucz: {key:<6} -> {record}")
        if not node.is_leaf:
            self._traverse_and_print(node.children[-1])

    def print_tree(self):
        print("\n--- Struktura B-Drzewa (Strony) ---")
        if self.root_id is not None:
            self._print_node(self.root_id, 0)
        else:
            print("Drzewo puste.")
        print("-----------------------------------\n")

    def _print_node(self, node_id, level):
        node = self.get_node(node_id)
        if node:
            indent = "  " * level
            print(f"{indent}Strona {node_id}: {node.keys}")
            if not node.is_leaf:
                for child_id in node.children:
                    self._print_node(child_id, level + 1)


# --- NARZĘDZIA POMOCNICZE ---

def clean_files(prefixes):
    for base in prefixes:
        filename = base + ".bin"
        if os.path.exists(filename):
            try:
                os.remove(filename)
            except OSError:
                pass


def print_data_file(data_mgr):
    print("\n--- Plik Danych (Kolejność fizyczna na dysku) ---")
    max_id = data_mgr.disk.get_next_page_id()
    for page_id in range(1, max_id):
        obj = data_mgr.read_record(page_id)
        if obj and isinstance(obj, Record):
            status = "WOLNY" if page_id in data_mgr.free_pages else "ZAJĘTY"
            print(f"Strona {page_id} [{status}]: {obj}")
    print(f"Wolne strony: {data_mgr.free_pages}")
    print("-------------------------------------------------\n")


def generate_random_records(btree, count):
    print(f"Generowanie {count} losowych rekordów...")
    max_range = max(count * 10, 10000)
    try:
        keys = random.sample(range(1, max_range), count)
    except ValueError:
        keys = random.sample(range(1, count * 2), count)

    added_count = 0
    stats.reset()
    for key in keys:
        num_count = random.randint(3, 8)
        numbers = [random.randint(1, 100) for _ in range(num_count)]
        if btree.insert(key, numbers):
            added_count += 1
    print(f"Sukces: Dodano {added_count} rekordów.")
    print(f"IO: {stats}")


def run_script(btree, filename):
    print(f"--- Uruchamianie skryptu: {filename} ---")
    try:
        with open(filename, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'): continue
                parts = line.split()
                cmd = parts[0].upper()
                print(f"CMD: {line}")
                stats.reset()
                try:
                    if cmd == "ADD":
                        key = int(parts[1])
                        nums = [int(x) for x in parts[2:]]
                        btree.insert(key, nums)
                    elif cmd == "DEL":
                        key = int(parts[1])
                        btree.delete(key)
                    elif cmd == "UPD":
                        key = int(parts[1])
                        nums = [int(x) for x in parts[2:]]
                        btree.update(key, nums)
                    else:
                        print("Nieznana komenda")
                    print(f"   -> IO: {stats}")
                except Exception as e:
                    print(f"   -> Błąd wykonania: {e}")
    except FileNotFoundError:
        print("Nie znaleziono pliku skryptu.")


def run_experiment():
    print("\n=== EKSPERYMENT ===")
    degrees = [2, 5, 10]
    record_counts = [50, 100, 200, 500]
    results = {}

    print(f"{'d':<5} | {'N':<5} | {'Avg Read':<10} | {'Avg Write':<10} | {'Idx Size':<10}")
    print("-" * 55)

    for d in degrees:
        results[d] = {'N': [], 'reads': [], 'writes': [], 'idx_size': []}
        for N in record_counts:
            clean_files(["exp_index", "exp_data"])
            disk_idx = DiskManager("exp_index")
            disk_dat = DiskManager("exp_data")
            mgr = DataFileManager(disk_dat)
            btree = BTree(d, disk_idx, mgr)

            keys = list(range(1, N + 1))
            random.shuffle(keys)

            stats.reset()
            for k in keys:
                nums = [random.randint(1, 100) for _ in range(3)]
                btree.insert(k, nums)

            avg_r = stats.reads / N
            avg_w = stats.writes / N
            idx_size = disk_idx.get_file_size()

            results[d]['N'].append(N)
            results[d]['reads'].append(avg_r)
            results[d]['writes'].append(avg_w)
            results[d]['idx_size'].append(idx_size)

            print(f"{d:<5} | {N:<5} | {avg_r:<10.2f} | {avg_w:<10.2f} | {idx_size:<10}")
            disk_idx.close()
            disk_dat.close()

    generate_plots(results)


def generate_plots(results):
    # Wykres 1: Odczyty
    plt.figure(figsize=(10, 5))
    for d, data in results.items():
        plt.plot(data['N'], data['reads'], marker='o', label=f'd={d}')
    plt.title('Średnie odczyty vs N')
    plt.xlabel('Liczba rekordów (N)')
    plt.ylabel('Średnie odczyty')
    plt.legend()
    plt.grid(True)
    plt.savefig('wykres_odczyty.png')
    print("Wygenerowano: wykres_odczyty.png")

    # Wykres 2: Rozmiar Indeksu
    plt.figure(figsize=(10, 5))
    for d, data in results.items():
        plt.plot(data['N'], data['idx_size'], marker='s', linestyle='--', label=f'd={d}')
    plt.title('Rozmiar pliku indeksu vs N')
    plt.xlabel('Liczba rekordów (N)')
    plt.ylabel('Rozmiar (Bajty)')
    plt.legend()
    plt.grid(True)
    plt.savefig('wykres_rozmiar.png')
    print("Wygenerowano: wykres_rozmiar.png")


def interactive_mode():
    idx_filename = "main_index"
    dat_filename = "main_data"

    idx_disk = DiskManager(idx_filename)
    dat_disk = DiskManager(dat_filename)
    data_mgr = DataFileManager(dat_disk)

    btree = BTree(2, idx_disk, data_mgr)

    print("System B-Drzewa (Zadanie 2) - BINARY MODE.")
    print("Wpisz 'help' aby zobaczyć listę komend.")

    while True:
        try:
            cmd_input = input("\n> ").strip()
            if not cmd_input: continue
            cmd_parts = cmd_input.split()
            op = cmd_parts[0].lower()

            if op == "exit":
                idx_disk.close()
                dat_disk.close()
                break
            elif op == "add":
                if len(cmd_parts) < 3:
                    print("Użycie: add <key> <n1> ...")
                    continue
                try:
                    key = int(cmd_parts[1])
                    nums = [int(x) for x in cmd_parts[2:]]
                    stats.reset()
                    btree.insert(key, nums)
                    print(f"IO: {stats}")
                except ValueError:
                    print("Błąd danych.")
            elif op == "upd":
                if len(cmd_parts) < 3:
                    print("Użycie: upd <key> <n1> ...")
                    continue
                try:
                    key = int(cmd_parts[1])
                    nums = [int(x) for x in cmd_parts[2:]]
                    stats.reset()
                    btree.update(key, nums)
                    print(f"IO: {stats}")
                except ValueError:
                    print("Błąd danych.")
            elif op == "find":
                if len(cmd_parts) < 2: continue
                try:
                    key = int(cmd_parts[1])
                    stats.reset()
                    rec, node_id, idx = btree.search(key)
                    if rec:
                        print(f"Znaleziono: {rec} (Node: {node_id}, Idx: {idx})")
                    else:
                        print("Nie znaleziono.")
                    print(f"IO: {stats}")
                except ValueError:
                    print("Błąd klucza.")
            elif op == "del":
                if len(cmd_parts) < 2: continue
                try:
                    key = int(cmd_parts[1])
                    stats.reset()
                    btree.delete(key)
                    print(f"IO: {stats}")
                except ValueError:
                    print("Błąd klucza.")
            elif op == "print":
                btree.print_tree()
                print_data_file(data_mgr)

            elif op == "scan":
                stats.reset()
                btree.print_ordered_records()
                print(f"IO (Przeglądanie całości): {stats}")

            elif op == "script":
                if len(cmd_parts) < 2: continue
                run_script(btree, cmd_parts[1])
            elif op == "exp":
                run_experiment()
            elif op == "random":
                if len(cmd_parts) < 2: continue
                try:
                    generate_random_records(btree, int(cmd_parts[1]))
                except ValueError:
                    pass
            elif op == "clear":
                idx_disk.clear()
                dat_disk.clear()
                btree = BTree(2, idx_disk, data_mgr)
                print("Baza wyczyszczona.")
            elif op == "help":
                print("Komendy:")
                print("  add <id> <n1>... - dodaj rekord")
                print("  upd <id> <n1>... - aktualizuj rekord")
                print("  del <id>         - usuń rekord")
                print("  find <id>        - szukaj rekordu")
                print("  scan             - wyświetl WSZYSTKIE rekordy posortowane (In-Order)")
                print("  print            - wyświetl strukturę techniczną (strony/drzewo)")
                print("  script <file>    - wykonaj skrypt")
                print("  exp              - eksperyment")
                print("  random <n>       - generuj losowe dane")
                print("  clear            - wyczyść bazę")
                print("  exit             - wyjście")
            else:
                print("Nieznana komenda.")
        except Exception as e:
            print(f"Błąd pętli: {e}")


if __name__ == "__main__":
    interactive_mode()
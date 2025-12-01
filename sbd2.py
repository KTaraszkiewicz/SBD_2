import sys
import random
import pickle
import math
import os
import struct
import matplotlib.pyplot as plt

# --- KONFIGURACJA SYMULACJI ---
PAGE_SIZE = 512  # Stały rozmiar strony w bajtach (można zmienić np. na 1024, 4096)

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
    Strona 0 jest zarezerwowana na metadane (Next_Page_ID, Root_ID).
    """
    def __init__(self, filename):
        self.filename = filename + ".bin"
        self.page_size = PAGE_SIZE
        
        # Otwieramy plik w trybie binarnym do odczytu i zapisu
        # Jeśli plik nie istnieje, tworzymy go i inicjalizujemy Superblock (strona 0)
        if not os.path.exists(self.filename):
            with open(self.filename, 'wb') as f:
                # Format: [Next_Page_ID (4B int)] [Root_ID (4B int)] [Padding...]
                # -1 oznacza brak root_id
                f.write(struct.pack('ii', 1, -1)) 
                f.write(b'\x00' * (self.page_size - 8))
        
        self.file = open(self.filename, 'r+b')

    def _read_metadata(self):
        """Odczytuje Next_Page_ID i Root_ID ze strony 0."""
        self.file.seek(0)
        data = self.file.read(8)
        return struct.unpack('ii', data)

    def _write_metadata(self, next_page_id, root_id):
        """Zapisuje metadane na stronie 0."""
        self.file.seek(0)
        self.file.write(struct.pack('ii', next_page_id, root_id))

    def get_root_id(self):
        """Pobiera ID korzenia (zastępuje dictionary['root_id'])."""
        _, root_id = self._read_metadata()
        return root_id if root_id != -1 else None

    def set_root_id(self, root_id):
        """Ustawia ID korzenia."""
        next_id, _ = self._read_metadata()
        self._write_metadata(next_id, root_id if root_id is not None else -1)

    def get_next_page_id(self):
        """Zwraca licznik stron (do iteracji)."""
        next_id, _ = self._read_metadata()
        return next_id

    def read_page(self, page_id):
        if page_id is None: return None
        stats.reads += 1
        
        offset = page_id * self.page_size
        self.file.seek(offset)
        raw_data = self.file.read(self.page_size)
        
        # Jeśli odczytano puste bajty lub same zera (oznaczone jako usunięte), zwróć None
        if not raw_data or raw_data == b'\x00' * self.page_size:
            return None
        
        try:
            return pickle.loads(raw_data)
        except (pickle.UnpicklingError, EOFError):
            return None

    def write_page(self, page_id, data_obj):
        stats.writes += 1
        next_id, root_id = self._read_metadata()
        
        # Jeśli nie podano ID, przydziel nowe
        if page_id is None:
            page_id = next_id
            next_id += 1
            self._write_metadata(next_id, root_id)
        
        # Serializacja
        serialized_data = pickle.dumps(data_obj)
        
        # Sprawdzenie czy dane mieszczą się w bloku
        if len(serialized_data) > self.page_size:
            # W realnym systemie tutaj nastąpiłaby fragmentacja lub overflow pages.
            # W symulacji rzucamy błąd, sugerując zwiększenie PAGE_SIZE.
            raise ValueError(f"CRITICAL: Obiekt za duży ({len(serialized_data)} B) dla strony ({self.page_size} B). Zwiększ PAGE_SIZE w kodzie.")
            
        # Padding (dopełnienie zerami do pełnego rozmiaru strony)
        padding = b'\x00' * (self.page_size - len(serialized_data))
        final_block = serialized_data + padding
        
        offset = page_id * self.page_size
        self.file.seek(offset)
        self.file.write(final_block)
        
        return page_id

    def delete_page(self, page_id):
        # Nadpisujemy zerami
        offset = page_id * self.page_size
        self.file.seek(offset)
        self.file.write(b'\x00' * self.page_size)

    def get_file_size(self):
        """Zwraca rozmiar fizyczny pliku."""
        self.file.flush()
        return os.path.getsize(self.filename)

    def close(self):
        self.file.close()

    def clear(self):
        """Resetuje plik bazy."""
        self.file.close()
        if os.path.exists(self.filename):
            os.remove(self.filename)
        # Reinit
        with open(self.filename, 'wb') as f:
            f.write(struct.pack('ii', 1, -1)) 
            f.write(b'\x00' * (self.page_size - 8))
        self.file = open(self.filename, 'r+b')

# --- STRUKTURY DANYCH ---

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
        self.keys = []      # Lista kluczy
        self.values = []    # Adresy rekordów
        self.children = []  # ID stron dzieci
        
    def __repr__(self):
        return f"Node(Leaf={self.is_leaf}, Keys={self.keys})"

# --- MANAGERY PLIKÓW ---

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
        # Oznaczamy stronę jako wolną w managerze i czyścimy na dysku
        self.free_pages.append(page_id)
        self.disk.delete_page(page_id)

# --- IMPLEMENTACJA B-DRZEWA ---

class BTree:
    def __init__(self, d, index_disk, data_manager):
        self.d = d 
        self.disk = index_disk
        self.data_mgr = data_manager
        
        # Pobieramy ID korzenia z metadanych (strona 0)
        self.root_id = self.disk.get_root_id()
        
        if self.root_id is None:
            # Tworzenie nowego drzewa
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
            if node.is_leaf:
                return self.data_mgr.read_record(node.values[i]), node_id, i
            else:
                return self.data_mgr.read_record(node.values[i]), node_id, i

        if node.is_leaf:
            return None, None, None 

        return self.search(key, node.children[i])

    # --- WSTAWIANIE ---
    def insert(self, key, numbers):
        rec, _, _ = self.search(key)
        if rec:
            print(f"Błąd: Klucz {key} już istnieje.")
            return False

        new_record = Record(key, numbers)
        try:
            data_addr = self.data_mgr.insert_record(new_record)
        except ValueError as e:
            print(f"Błąd zapisu rekordu: {e}")
            return False

        root = self.get_node(self.root_id)
        # Sprawdzenie przepełnienia korzenia
        if len(root.keys) == (2 * self.d):
            new_root = BTreeNode(is_leaf=False)
            new_root.children.append(self.root_id)
            self.split_child(new_root, 0)
            
            # Zaktualizuj ID korzenia
            self.update_root(self.disk.write_page(None, new_root))
            self.insert_non_full(new_root, key, data_addr)
        else:
            self.insert_non_full(root, key, data_addr)
            self.save_node(self.root_id, root)
        return True

    def split_child(self, parent, index):
        child_id = parent.children[index]
        child = self.get_node(child_id)
        
        new_node = BTreeNode(is_leaf=child.is_leaf)
        
        mid_key = child.keys[self.d]
        mid_val = child.values[self.d] if len(child.values) > self.d else None

        new_node.keys = child.keys[self.d+1:]
        new_node.values = child.values[self.d+1:]

        if not child.is_leaf:
            new_node.children = child.children[self.d+1:]
        
        child.keys = child.keys[:self.d]
        child.values = child.values[:self.d]
        if not child.is_leaf:
            child.children = child.children[:self.d+1]

        new_node_id = self.disk.write_page(None, new_node)
        self.save_node(child_id, child)

        parent.children.insert(index + 1, new_node_id)
        parent.keys.insert(index, mid_key)
        parent.values.insert(index, mid_val)

    def insert_non_full(self, node_obj, key, data_addr):
        i = len(node_obj.keys) - 1
        if node_obj.is_leaf:
            node_obj.keys.append(0)
            node_obj.values.append(0)
            while i >= 0 and key < node_obj.keys[i]:
                node_obj.keys[i+1] = node_obj.keys[i]
                node_obj.values[i+1] = node_obj.values[i]
                i -= 1
            node_obj.keys[i+1] = key
            node_obj.values[i+1] = data_addr
        else:
            while i >= 0 and key < node_obj.keys[i]:
                i -= 1
            i += 1
            
            child_id = node_obj.children[i]
            child = self.get_node(child_id)
            
            if len(child.keys) == 2 * self.d:
                self.split_child(node_obj, i)
                if key > node_obj.keys[i]:
                    i += 1
                child_id = node_obj.children[i]
                child = self.get_node(child_id)
            
            self.insert_non_full(child, key, data_addr)
            self.save_node(child_id, child)

    # --- USUWANIE ---
    def delete(self, key):
        if self.search(key)[0] is None:
            print(f"Klucz {key} nie istnieje.")
            return False
            
        root = self.get_node(self.root_id)
        self._delete_recursive(root, self.root_id, key)
        
        if len(root.keys) == 0 and not root.is_leaf:
            self.disk.delete_page(self.root_id)
            self.update_root(root.children[0])
        return True
    
    # --- UPDATE (Dla obsługi skryptu) ---
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
                print(f"Błąd aktualizacji (za dużo danych?): {e}")
                return False
        else:
            print(f"Klucz {key} nie istnieje - brak aktualizacji.")
            return False

    def _delete_recursive(self, node, node_id, key):
        idx = 0
        while idx < len(node.keys) and key > node.keys[idx]:
            idx += 1
        
        if idx < len(node.keys) and node.keys[idx] == key:
            if node.is_leaf:
                self.data_mgr.delete_record(node.values[idx])
                del node.keys[idx]
                del node.values[idx]
                self.save_node(node_id, node)
            else:
                pred_child_id = node.children[idx]
                pred_node = self.get_node(pred_child_id)
                while not pred_node.is_leaf:
                    pred_child_id = pred_node.children[-1]
                    pred_node = self.get_node(pred_child_id)
                
                predecessor_key = pred_node.keys[-1]
                predecessor_val = pred_node.values[-1]
                
                node.keys[idx] = predecessor_key
                node.values[idx] = predecessor_val
                self.save_node(node_id, node)
                
                self._delete_recursive(self.get_node(node.children[idx]), node.children[idx], predecessor_key)
        
        else:
            if node.is_leaf: return 

            child_id = node.children[idx]
            child = self.get_node(child_id)

            if len(child.keys) == self.d: # Warunek minimalnego wypełnienia
                self._fix_child(node, idx, child, child_id)
                if idx > len(node.keys): idx -= 1
                child_id = node.children[idx]
                child = self.get_node(child_id)

            self._delete_recursive(child, child_id, key)

    def _fix_child(self, parent, idx, child, child_id):
        if idx > 0:
            left_sibling_id = parent.children[idx-1]
            left_sibling = self.get_node(left_sibling_id)
            if len(left_sibling.keys) > self.d:
                child.keys.insert(0, parent.keys[idx-1])
                child.values.insert(0, parent.values[idx-1])
                if not child.is_leaf:
                    child.children.insert(0, left_sibling.children.pop())
                
                parent.keys[idx-1] = left_sibling.keys.pop()
                parent.values[idx-1] = left_sibling.values.pop()
                
                self.save_node(child_id, child)
                self.save_node(left_sibling_id, left_sibling)
                self.save_node(None, parent)
                return

        if idx < len(parent.children) - 1:
            right_sibling_id = parent.children[idx+1]
            right_sibling = self.get_node(right_sibling_id)
            if len(right_sibling.keys) > self.d:
                child.keys.append(parent.keys[idx])
                child.values.append(parent.values[idx])
                if not child.is_leaf:
                    child.children.append(right_sibling.children.pop(0))
                
                parent.keys[idx] = right_sibling.keys.pop(0)
                parent.values[idx] = right_sibling.values.pop(0)
                
                self.save_node(child_id, child)
                self.save_node(right_sibling_id, right_sibling)
                self.save_node(None, parent)
                return

        if idx > 0:
            left_sibling_id = parent.children[idx-1]
            left_sibling = self.get_node(left_sibling_id)
            
            left_sibling.keys.append(parent.keys[idx-1])
            left_sibling.values.append(parent.values[idx-1])
            left_sibling.keys.extend(child.keys)
            left_sibling.values.extend(child.values)
            if not left_sibling.is_leaf:
                left_sibling.children.extend(child.children)
            
            del parent.keys[idx-1]
            del parent.values[idx-1]
            del parent.children[idx]
            
            self.disk.delete_page(child_id)
            self.save_node(left_sibling_id, left_sibling)
            self.save_node(None, parent)
        else:
            right_sibling_id = parent.children[idx+1]
            right_sibling = self.get_node(right_sibling_id)
            
            child.keys.append(parent.keys[idx])
            child.values.append(parent.values[idx])
            child.keys.extend(right_sibling.keys)
            child.values.extend(right_sibling.values)
            if not child.is_leaf:
                child.children.extend(right_sibling.children)
                
            del parent.keys[idx]
            del parent.values[idx]
            del parent.children[idx+1]
            
            self.disk.delete_page(right_sibling_id)
            self.save_node(child_id, child)
            self.save_node(None, parent)

    def print_tree(self):
        print("\n--- Struktura B-Drzewa ---")
        if self.root_id is not None:
            self._print_node(self.root_id, 0)
        else:
            print("Drzewo puste.")
        print("--------------------------\n")

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
    """Usuwa pliki bazy danych przed eksperymentem."""
    for base in prefixes:
        # Teraz szukamy głównie .bin
        filename = base + ".bin"
        if os.path.exists(filename):
            try:
                os.remove(filename)
            except OSError:
                pass

def print_data_file(data_mgr):
    print("\n--- Plik Danych (Rekordy) ---")
    # Iteracja po stronach w surowym pliku:
    # Pobieramy max ID z metadanych
    max_id = data_mgr.disk.get_next_page_id()
    
    # Przeglądamy od strony 1 (0 to metadane) do max_id
    for page_id in range(1, max_id):
        obj = data_mgr.read_record(page_id)
        if obj and isinstance(obj, Record):
            status = "WOLNY" if page_id in data_mgr.free_pages else "ZAJĘTY"
            print(f"Strona {page_id} [{status}]: {obj}")
            
    print(f"Lista wolnych stron: {data_mgr.free_pages}")
    print("-----------------------------")

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
            
    print(f"Sukces: Dodano {added_count} nowych rekordów.")
    print(f"Koszt operacji (IO): {stats}")

def run_script(btree, filename):
    """
    Wykonuje komendy z pliku tekstowego.
    """
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
                    print(f"   -> Błąd wykonania linii: {e}")
                    
    except FileNotFoundError:
        print("Nie znaleziono pliku skryptu.")

def run_experiment():
    print("\n=== ROZPOCZYNANIE EKSPERYMENTU (RAW BINARY) ===")
    print(f"PAGE_SIZE ustawione na: {PAGE_SIZE} Bajtów")
    
    degrees = [2, 5, 10]
    record_counts = [50, 100, 200, 500]
    
    results = {}

    print(f"{'d':<5} | {'N':<5} | {'Avg Read':<10} | {'Avg Write':<10} | {'Idx Size(B)':<12} | {'Dat Size(B)':<12}")
    print("-" * 75)
    
    for d in degrees:
        results[d] = {
            'N': [], 'reads': [], 'writes': [], 'idx_size': [], 'dat_size': []
        }
        for N in record_counts:
            # 1. Wyczyść stare pliki
            clean_files(["exp_index", "exp_data"])
            
            # 2. Inicjalizacja (CustomDiskManager)
            disk_idx = DiskManager("exp_index")
            disk_dat = DiskManager("exp_data")
            mgr = DataFileManager(disk_dat)
            btree = BTree(d, disk_idx, mgr)
            
            # 3. Wykonanie operacji
            keys = list(range(1, N + 1))
            random.shuffle(keys)
            
            stats.reset()
            for k in keys:
                nums = [random.randint(1, 100) for _ in range(3)]
                btree.insert(k, nums)
            
            # 4. Zbieranie metryk
            avg_r = stats.reads / N
            avg_w = stats.writes / N
            idx_size = disk_idx.get_file_size()
            dat_size = disk_dat.get_file_size()
            
            results[d]['N'].append(N)
            results[d]['reads'].append(avg_r)
            results[d]['writes'].append(avg_w)
            results[d]['idx_size'].append(idx_size)
            results[d]['dat_size'].append(dat_size)
            
            print(f"{d:<5} | {N:<5} | {avg_r:<10.2f} | {avg_w:<10.2f} | {idx_size:<12} | {dat_size:<12}")
            
            # Zamknięcie deskryptorów
            disk_idx.close()
            disk_dat.close()

    generate_plots(results)

def generate_plots(results):
    # Wykres 1: Odczyty vs N
    plt.figure(figsize=(10, 5))
    for d, data in results.items():
        plt.plot(data['N'], data['reads'], marker='o', label=f'd={d}')
    plt.title(f'Średnia liczba odczytów vs N (Page={PAGE_SIZE}B)')
    plt.xlabel('Liczba rekordów (N)')
    plt.ylabel('Średnie odczyty dyskowe')
    plt.legend()
    plt.grid(True)
    plt.savefig('wykres_odczyty.png')
    print("\nWygenerowano wykres: wykres_odczyty.png")

    # Wykres 2: Rozmiar Indeksu vs N
    plt.figure(figsize=(10, 5))
    for d, data in results.items():
        plt.plot(data['N'], data['idx_size'], marker='s', linestyle='--', label=f'd={d}')
    plt.title(f'Rozmiar pliku indeksu vs N (Page={PAGE_SIZE}B)')
    plt.xlabel('Liczba rekordów (N)')
    plt.ylabel('Rozmiar pliku (Bajty)')
    plt.legend()
    plt.grid(True)
    plt.savefig('wykres_rozmiar.png')
    print("Wygenerowano wykres: wykres_rozmiar.png")

def interactive_mode():
    idx_filename = "main_index"
    dat_filename = "main_data"
    
    idx_disk = DiskManager(idx_filename)
    dat_disk = DiskManager(dat_filename)
    data_mgr = DataFileManager(dat_disk)
    
    btree = BTree(2, idx_disk, data_mgr)

    print("System B-Drzewa (Zadanie 2) - BINARY MODE.")
    print(f"Pliki bazy danych: {idx_filename}.bin, {dat_filename}.bin")
    print("Wpisz 'help' aby zobaczyć listę komend.")
    
    while True:
        try:
            cmd_input = input("> ").strip()
            if not cmd_input: continue
            
            cmd_parts = cmd_input.split()
            op = cmd_parts[0].lower()
            
            if op == "exit":
                idx_disk.close()
                dat_disk.close()
                break
                
            elif op == "add": 
                if len(cmd_parts) < 3:
                    print("Użycie: add <key> <n1> <n2> ...")
                    continue
                try:
                    key = int(cmd_parts[1])
                    nums = [int(x) for x in cmd_parts[2:]]
                    stats.reset()
                    btree.insert(key, nums)
                    print(f"IO: {stats}")
                except ValueError as e:
                    print(f"Błąd: {e}")

            elif op == "upd":
                if len(cmd_parts) < 3:
                    print("Użycie: upd <key> <n1> <n2> ...")
                    continue
                try:
                    key = int(cmd_parts[1])
                    nums = [int(x) for x in cmd_parts[2:]]
                    stats.reset()
                    btree.update(key, nums)
                    print(f"IO: {stats}")
                except ValueError as e:
                    print(f"Błąd: {e}")
                
            elif op == "find":
                if len(cmd_parts) < 2: continue
                try:
                    key = int(cmd_parts[1])
                    stats.reset()
                    rec, node_id, idx = btree.search(key)
                    if rec:
                        print(f"Znaleziono: {rec} (Node: {node_id}, Index: {idx})")
                    else:
                        print("Nie znaleziono.")
                    print(f"IO: {stats}")
                except ValueError:
                    print("Błąd: Klucz musi być liczbą całkowitą.")
                
            elif op == "del":
                if len(cmd_parts) < 2: continue
                try:
                    key = int(cmd_parts[1])
                    stats.reset()
                    btree.delete(key)
                    print(f"IO: {stats}")
                except ValueError:
                    print("Błąd: Klucz musi być liczbą całkowitą.")

            elif op == "print":
                btree.print_tree()
                print_data_file(data_mgr)
                print(f"Rozmiar pliku indeksu: {idx_disk.get_file_size()} B")
                print(f"Rozmiar pliku danych: {dat_disk.get_file_size()} B")

            elif op == "script":
                if len(cmd_parts) < 2: 
                    print("Podaj nazwę pliku.")
                    continue
                run_script(btree, cmd_parts[1])

            elif op == "exp":
                run_experiment()
            
            elif op == "random":
                if len(cmd_parts) < 2: continue
                try:
                    generate_random_records(btree, int(cmd_parts[1]))
                except ValueError:
                    print("Podaj poprawną liczbę.")
                
            elif op == "clear":
                idx_disk.clear()
                dat_disk.clear()
                btree = BTree(2, idx_disk, data_mgr)
                print("Baza wyczyszczona.")

            elif op == "help":
                print("Komendy:")
                print("  add <id> <n1>...  - dodaj nowy rekord")
                print("  upd <id> <n1>...  - aktualizuj rekord")
                print("  del <id>          - usuń rekord")
                print("  find <id>         - szukaj rekordu")
                print("  script <file>     - wykonaj skrypt")
                print("  print             - pokaż strukturę i rozmiar")
                print("  exp               - eksperyment z wykresami")
                print("  random <n>        - generuj n rekordów")
                print("  clear             - wyczyść bazę")
                print("  exit              - wyjście")
            else:
                print("Nieznana komenda.")
                
        except Exception as e:
            print(f"Błąd krytyczny pętli: {e}")

if __name__ == "__main__":
    interactive_mode()
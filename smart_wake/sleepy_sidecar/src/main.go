package main

import (
	"encoding/csv"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"regexp"
	"strconv"
	"sync"
	"time"

	"github.com/znoxx/gowol"
)

const (
	sleep     string = "sleep"
	wake             = "wake"
	has_error        = "error"
)

var (
	goToServerRe   = regexp.MustCompile(`^\/go\/(.[a-zA-Z0-9_]*)$`)
	statusServerRe = regexp.MustCompile(`^\/status\/(sleep|wake)\/(.[a-zA-Z0-9_]*)$`)
	getServerRe    = regexp.MustCompile(`^\/status\/get\/(.[a-zA-Z0-9_]*)$`)
	liveProbeRe    = regexp.MustCompile(`^\/alive$`)
)

type server struct {
	ID      string `json:"id"`
	MAC     string `json:"mac"`
	STATUS  string `json:"status"`
	TIMEOUT int    `json:"timeout"`
	mu      sync.RWMutex
}

var Servers []server

func getServerById(id string) int {

	for index, _ := range Servers {
		if Servers[index].ID == id {
			return index
		}
	}
	return -1
}

func updateServerStatus(newState string, serverIndex int) {

	Servers[serverIndex].mu.Lock()
	Servers[serverIndex].STATUS = newState
	Servers[serverIndex].mu.Unlock()

	return
}

func getServerJson(serverIndex int) ([]byte, error) {

	Servers[serverIndex].mu.RLock()
	server_snap := Servers[serverIndex]
	Servers[serverIndex].mu.RUnlock()

	return json.Marshal(server_snap)
}

func wakeServer(serverIndex int) error {

	Servers[serverIndex].mu.RLock()
	status := Servers[serverIndex].STATUS
	mac := Servers[serverIndex].MAC
	Servers[serverIndex].mu.RUnlock()

	if status == sleep {
		log.Printf("Waking server index %d, mac: %s", serverIndex, mac)
		Servers[serverIndex].mu.Lock()
		if packet, err := gowol.NewMagicPacket(mac); err == nil {
			packet.Send("255.255.255.255")
			time.Sleep(time.Duration(Servers[serverIndex].TIMEOUT) * time.Second)
			Servers[serverIndex].STATUS = wake
			Servers[serverIndex].mu.Unlock()
		} else {
			Servers[serverIndex].STATUS = has_error
			Servers[serverIndex].mu.Unlock()
			log.Fatalf("Unable to send magic packet to server with index %d, error: %s", serverIndex, err)
			return err
		}

	} else {
		log.Printf("Server with index %+v already awake", serverIndex)
	}
	return nil
}

func ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("content-type", "application/json")
	switch {
	case r.Method == http.MethodGet && goToServerRe.MatchString(r.URL.Path):
		Go(w, r)
		return
	case r.Method == http.MethodPost && statusServerRe.MatchString(r.URL.Path):
		Status(w, r)
		return
	case r.Method == http.MethodGet && getServerRe.MatchString(r.URL.Path):
		Get(w, r)
		return
	case r.Method == http.MethodGet && liveProbeRe.MatchString(r.URL.Path):
		Alive(w, r)
		return
	default:
		notFound(w, r)
		return
	}
}

func Alive(w http.ResponseWriter, r *http.Request) {

	w.WriteHeader(http.StatusOK)
	w.Write([]byte("{\"status\": \"OK\"}"))
}

func Get(w http.ResponseWriter, r *http.Request) {
	matches := getServerRe.FindStringSubmatch(r.URL.Path)

	if len(matches) < 2 {
		notFound(w, r)
		return
	}

	serverIndex := getServerById(matches[1])

	if serverIndex < 0 {
		w.WriteHeader(http.StatusNotFound)
		w.Write([]byte("server not found"))
		return
	}

	jsonBytes, err := getServerJson(serverIndex)
	if err != nil {
		internalServerError(w, r, nil)
		return
	}
	w.WriteHeader(http.StatusOK)
	w.Write(jsonBytes)
}

func Go(w http.ResponseWriter, r *http.Request) {
	matches := goToServerRe.FindStringSubmatch(r.URL.Path)

	if len(matches) < 2 {
		notFound(w, r)
		return
	}

	serverIndex := getServerById(matches[1])

	if serverIndex < 0 {
		w.WriteHeader(http.StatusNotFound)
		w.Write([]byte("server not found"))
		return
	}

	error_on_wake := wakeServer(serverIndex)

	if error_on_wake == nil {
		updateServerStatus(wake, serverIndex)
	} else {
		internalServerError(w, r, []byte("failed to wake up"))
		return
	}

	jsonBytes, err := getServerJson(serverIndex)
	if err != nil {
		internalServerError(w, r, nil)
		return
	}
	w.WriteHeader(http.StatusOK)
	w.Write(jsonBytes)
}

func Status(w http.ResponseWriter, r *http.Request) {

	matches := statusServerRe.FindStringSubmatch(r.URL.Path)

	if len(matches) < 3 {
		notFound(w, r)
		return
	}
	mode := matches[1]
	id := matches[2]

	serverIndex := getServerById(id)

	if serverIndex < 0 {
		w.WriteHeader(http.StatusNotFound)
		w.Write([]byte("server not found"))
		return
	}
	updateServerStatus(mode, serverIndex)

	jsonBytes, err := getServerJson(serverIndex)
	if err != nil {
		internalServerError(w, r, nil)
		return
	}
	w.WriteHeader(http.StatusOK)
	w.Write(jsonBytes)
}

func internalServerError(w http.ResponseWriter, r *http.Request, message []byte) {
	w.WriteHeader(http.StatusInternalServerError)
	if message == nil {
		w.Write([]byte("internal server error"))
	} else {
		w.Write(message)
	}

}

func notFound(w http.ResponseWriter, r *http.Request) {
	w.WriteHeader(http.StatusNotFound)
	w.Write([]byte("not found"))
}

func main() {

	c := flag.String("config", "sidecar.conf", "config file")
	p := flag.Int("port", 10000, "port")
	a := flag.String("address", "0.0.0.0", "listen address")

	flag.Parse()

	config := *c
	port := *p
	address := *a

	f, err := os.Open(config)
	if err != nil {
		log.Fatal("Unable to read input file "+config, err)
	}
	defer f.Close()

	csvReader := csv.NewReader(f)
	records, err := csvReader.ReadAll()
	if err != nil {
		log.Fatal("Unable to parse file as CSV for "+config, err)
	}

	for index, value := range records {

		if len(value) != 3 {
			log.Fatalf("Config line should contain id,MAC,timeout values at line %d", index)
			os.Exit(1)
		} else {

			id := value[0]
			mac := value[1]
			timeout, err := strconv.Atoi(value[2])
			if err != nil {
				log.Fatalf("Timeout value at line %d parsing failed with error %s", index, err)
				os.Exit(1)
			}
			Servers = append(Servers, server{ID: id, MAC: mac, TIMEOUT: timeout, STATUS: sleep})
		}
	}

	log.Printf("CONFIG: %+v\n", config)
	log.Printf("ADDRESS: %+v\n", address)
	log.Printf("PORT: %+v\n", port)

	mux := http.NewServeMux()

	mux.HandleFunc("/", ServeHTTP)

	http.ListenAndServe(fmt.Sprintf("%s:%d", address, port), mux)
}

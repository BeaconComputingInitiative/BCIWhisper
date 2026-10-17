plugins {
    id("com.android.application")
}

android {
    namespace = "org.beaconcomputinginitiative.bciwhisper"
    compileSdk = 36
    ndkVersion = "25.2.9519653"

    defaultConfig {
        applicationId = "org.beaconcomputinginitiative.bciwhisper"
        minSdk = 28
        targetSdk = 36
        versionCode = 9
        versionName = "6.0-android-alpha9"

        ndk {
            abiFilters += listOf("arm64-v8a")
        }

        externalNativeBuild {
            cmake {
                arguments += listOf("-DCMAKE_BUILD_TYPE=Release")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    buildFeatures {
        buildConfig = true
    }

    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/whisper/CMakeLists.txt")
            version = "3.22.1"
        }
    }
}

dependencies {
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.github.wendykierp:JTransforms:3.1")
}

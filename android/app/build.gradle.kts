plugins {
    id("com.android.application")
}

android {
    namespace = "org.beaconcomputinginitiative.bciwhisper"
    compileSdk = 36

    defaultConfig {
        applicationId = "org.beaconcomputinginitiative.bciwhisper"
        minSdk = 28
        targetSdk = 36
        versionCode = 3
        versionName = "6.0-android-alpha3"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    buildFeatures {
        buildConfig = true
    }
}

dependencies {
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
}
